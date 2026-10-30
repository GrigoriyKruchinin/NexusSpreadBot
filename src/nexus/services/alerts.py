"""Alert delivery use case (runs in the ``alerts`` worker)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

import structlog

from nexus.domain.clock import Clock
from nexus.domain.errors import MessageGoneError, NotificationError
from nexus.domain.events import (
    AlertContext,
    AlertLifetime,
    EpisodeClosed,
    ExchangeRecovered,
    WatchdogAlert,
    WatchdogRecovered,
    event_from_payload,
)
from nexus.interfaces.notifications import DeliveryReceipt, INotifier, OutgoingMessage
from nexus.interfaces.repositories import (
    AlertDeliveryStatus,
    IAlertLogRepository,
    IAlertMessageRepository,
    IEvaluationRepository,
)
from nexus.notifications.formatting import OpportunityFormatter, SystemEventFormatter

log = structlog.get_logger(__name__)
CHANNEL = "telegram"
HOUR_MS = 3_600_000


class AlertOutcome(StrEnum):
    """Result of an alert task."""

    SENT = "sent"
    DUPLICATE = "duplicate"
    MISSING = "missing"
    NOT_ALERTABLE = "not_alertable"
    EXPIRED = "expired"
    SUPPRESSED = "suppressed"


class AlertService:
    """Loads an evaluation, renders it and delivers it exactly once (best effort).

    With a ``messages`` repository an episode is ONE Telegram message: NEW sends it, UPDATE edits
    it (a lost message is re-sent once), the episode-closed event edits it to CLOSED, and NEW
    messages over ``max_per_hour`` collapse into one "N more suppressed" summary.
    """

    def __init__(
        self,
        *,
        evaluations: IEvaluationRepository,
        alert_log: IAlertLogRepository,
        notifier: INotifier,
        clock: Clock,
        max_age_s: int,
        event_max_age_s: int = 300,
        opportunity_formatter: OpportunityFormatter | None = None,
        event_formatter: SystemEventFormatter | None = None,
        messages: IAlertMessageRepository | None = None,
        max_per_hour: int = 30,
    ) -> None:
        self._evaluations = evaluations
        self._alert_log = alert_log
        self._notifier = notifier
        self._clock = clock
        self._max_age_ms = max_age_s * 1000
        self._event_max_age_ms = event_max_age_s * 1000
        self._opportunity = opportunity_formatter or OpportunityFormatter()
        self._events = event_formatter or SystemEventFormatter()
        self._messages = messages
        self._max_per_hour = max_per_hour

    async def send_opportunity(
        self, evaluation_id: int, context: AlertContext | None = None
    ) -> AlertOutcome:
        """Deliver the alert for ``evaluation_id`` at most once, unless stale or invalid.

        The alert is claimed in the log *before* the message is sent, so an at-least-once
        broker redelivery (acks late, worker restart) cannot produce a second message.
        """
        evaluation = await self._evaluations.get(evaluation_id)
        if evaluation is None:
            return AlertOutcome.MISSING
        if not evaluation.is_alertable:
            return AlertOutcome.NOT_ALERTABLE
        age_ms = self._clock.now_ms() - evaluation.evaluated_at_ms
        if age_ms > self._max_age_ms:
            log.warning("alert_expired", evaluation_id=evaluation_id, age_ms=age_ms)
            return AlertOutcome.EXPIRED
        if not await self._alert_log.claim(evaluation_id, channel=CHANNEL):
            log.info("alert_duplicate", evaluation_id=evaluation_id)
            return AlertOutcome.DUPLICATE
        context = context or AlertContext()
        text = self._opportunity.render(evaluation, context)
        try:
            receipt = await self._deliver(text, context)
        except Exception as exc:
            # Release the claim so a Celery retry may try again (still bounded by max age).
            await self._alert_log.record(
                evaluation_id, channel=CHANNEL, status=AlertDeliveryStatus.FAILED, error=str(exc)
            )
            raise
        if receipt is None:
            await self._alert_log.record(
                evaluation_id, channel=CHANNEL, status=AlertDeliveryStatus.SUPPRESSED
            )
            log.warning("alert_suppressed", evaluation_id=evaluation_id, route=evaluation.route_key)
            return AlertOutcome.SUPPRESSED
        await self._alert_log.record(
            evaluation_id,
            channel=CHANNEL,
            status=AlertDeliveryStatus.SENT,
            message_id=receipt.message_id,
        )
        await self._remember(evaluation_id, context, receipt)
        log.info("alert_sent", evaluation_id=evaluation_id, route=evaluation.route_key)
        return AlertOutcome.SENT

    async def _deliver(self, text: str, context: AlertContext) -> DeliveryReceipt | None:
        """Send or edit the episode's message; ``None`` = suppressed (nothing was sent).

        Per episode the order is NEW -> UPDATE* -> CLOSED over ONE message:
        a NEW that finds a stored message (late retry) edits it instead of sending a duplicate;
        an UPDATE without a stored message (its NEW was suppressed by the cap or is still being
        retried) is dropped, because sending it would orphan the message the NEW will create.
        Such a dropped UPDATE is not replayed: growth is announced at the next threshold.
        """
        if self._messages is None or context.episode_id is None:
            return await self._send_new(text)
        existing = await self._messages.get_episode_message(context.episode_id)
        if existing is None:
            if context.realert:
                log.info("alert_update_no_message", episode_id=context.episode_id)
                return None
            return await self._send_new(text)
        try:
            return await self._notifier.edit(existing.message_id, OutgoingMessage(text))
        except MessageGoneError as exc:
            # Deleted or too old to edit: send once more and store the new id.
            log.warning("alert_message_gone", episode_id=context.episode_id, error=str(exc))
        return await self._send_new(text)

    async def _send_new(self, text: str, *, silent: bool = False) -> DeliveryReceipt | None:
        """Send under the hourly budget (``None`` = over the cap, folded into the summary)."""
        if self._messages is None:
            return await self._notifier.send(OutgoingMessage(text=text, silent=silent))
        window = self._window_start_ms()
        if not await self._messages.try_consume(window, self._max_per_hour):
            await self._summarize_suppressed(window)
            return None
        try:
            return await self._notifier.send(OutgoingMessage(text=text, silent=silent))
        except BaseException:
            await self._messages.refund(window)
            raise

    def _window_start_ms(self) -> int:
        now = self._clock.now_ms()
        return now - now % HOUR_MS

    async def _summarize_suppressed(self, window_ms: int) -> None:
        """One 'N more suppressed' message per hour, edited as the count grows."""
        if self._messages is None:  # pragma: no cover - only called with a repository
            return
        summary = await self._messages.record_suppressed(window_ms)
        message = OutgoingMessage(
            text=self._opportunity.render_suppressed(summary.suppressed, self._max_per_hour),
            silent=True,
        )
        try:
            if summary.message_id is not None:
                try:
                    await self._notifier.edit(summary.message_id, message)
                except MessageGoneError:
                    pass
                else:
                    return
            receipt = await self._notifier.send(message)
            if receipt.message_id is not None:
                await self._messages.set_summary_message(window_ms, receipt.message_id)
        except NotificationError as exc:  # the summary is a hint: never fail the alert task for it
            log.warning("suppressed_summary_failed", error=str(exc))

    async def _remember(
        self, evaluation_id: int, context: AlertContext, receipt: DeliveryReceipt
    ) -> None:
        """Store the message with what it was rendered from (CLOSED and restarts reuse it)."""
        if self._messages is None or context.episode_id is None:
            return
        if receipt.message_id is None:
            log.warning("alert_no_message_id", episode_id=context.episode_id)
            return
        await self._messages.save_episode_message(
            context.episode_id,
            message_id=receipt.message_id,
            evaluation_id=evaluation_id,
            context=context.to_payload(),
        )

    async def _close_message(self, event: EpisodeClosed) -> AlertOutcome:
        """Edit the episode's message to CLOSED, or drop the close (never a standalone message).

        A standalone "closed" message would bypass the hourly cap and announce an alert the user
        never saw (its NEW was suppressed), so without an editable message the close is silent.
        """
        if self._messages is None or event.episode_id is None:  # pragma: no cover - guarded
            return AlertOutcome.MISSING
        stored = await self._messages.get_episode_message(event.episode_id)
        if stored is None:
            log.info("alert_close_no_message", episode_id=event.episode_id)
            return AlertOutcome.SUPPRESSED
        evaluation = await self._evaluations.get(stored.evaluation_id)
        if evaluation is None or evaluation.breakdown is None:
            log.warning("alert_close_no_evaluation", episode_id=event.episode_id)
            return AlertOutcome.MISSING
        context = AlertContext.from_payload(stored.context)
        if event.opened_at_ms is not None:
            # The spread lived until its last qualifying evaluation (the gap is not lifetime).
            end = event.last_seen_at_ms or event.closed_at_ms or event.opened_at_ms
            context = replace(
                context, lifetime=AlertLifetime(event.opened_at_ms, end, closed_at_ms=end)
            )
        text = self._opportunity.render_closed(
            evaluation, context, peak_net_pct=_decimal(event.peak_net_pct)
        )
        try:
            await self._notifier.edit(stored.message_id, OutgoingMessage(text=text, silent=True))
        except MessageGoneError as exc:
            log.warning("alert_message_gone", episode_id=event.episode_id, error=str(exc))
            return AlertOutcome.MISSING
        log.info("alert_closed_edited", episode_id=event.episode_id)
        return AlertOutcome.SENT

    async def send_event(self, payload: dict[str, Any]) -> AlertOutcome:
        """Render and deliver a system event payload unless it is older than the event max age.

        Stale events (e.g. an ``exchange_down`` retried for minutes after the exchange has
        already recovered) would be misleading, so they are dropped. Watchdog events never expire.
        """
        event = event_from_payload(payload)
        if (
            isinstance(event, EpisodeClosed)
            and self._messages is not None
            and event.episode_id is not None
        ):
            return await self._close_message(event)  # an edit is harmless late: no expiry check
        emitted_at_ms = payload.get("emitted_at_ms")
        # Watchdog events are state-gated (one per incident, never misleading when late) and the
        # incident is already marked as announced, so they must survive an alerts-worker outage.
        if isinstance(emitted_at_ms, int) and not isinstance(
            event, WatchdogAlert | WatchdogRecovered
        ):
            age_ms = self._clock.now_ms() - emitted_at_ms
            if age_ms > self._event_max_age_ms:
                log.warning("event_expired", kind=event.kind, age_ms=age_ms)
                return AlertOutcome.EXPIRED
        silent = isinstance(event, ExchangeRecovered | EpisodeClosed | WatchdogRecovered)
        await self._notifier.send(OutgoingMessage(text=self._events.render(event), silent=silent))
        log.info("event_sent", kind=event.kind)
        return AlertOutcome.SENT


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
