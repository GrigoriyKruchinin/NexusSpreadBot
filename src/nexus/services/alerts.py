"""Alert delivery use case (runs in the ``alerts`` worker)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import structlog

from nexus.domain.clock import Clock
from nexus.domain.events import (
    AlertContext,
    EpisodeClosed,
    ExchangeRecovered,
    WatchdogRecovered,
    event_from_payload,
)
from nexus.interfaces.notifications import INotifier, OutgoingMessage
from nexus.interfaces.repositories import (
    AlertDeliveryStatus,
    IAlertLogRepository,
    IEvaluationRepository,
)
from nexus.notifications.formatting import OpportunityFormatter, SystemEventFormatter

log = structlog.get_logger(__name__)
CHANNEL = "telegram"


class AlertOutcome(StrEnum):
    """Result of an alert task."""

    SENT = "sent"
    DUPLICATE = "duplicate"
    MISSING = "missing"
    NOT_ALERTABLE = "not_alertable"
    EXPIRED = "expired"


class AlertService:
    """Loads an evaluation, renders it and delivers it exactly once (best effort)."""

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
    ) -> None:
        self._evaluations = evaluations
        self._alert_log = alert_log
        self._notifier = notifier
        self._clock = clock
        self._max_age_ms = max_age_s * 1000
        self._event_max_age_ms = event_max_age_s * 1000
        self._opportunity = opportunity_formatter or OpportunityFormatter()
        self._events = event_formatter or SystemEventFormatter()

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
        text = self._opportunity.render(evaluation, context)
        try:
            receipt = await self._notifier.send(OutgoingMessage(text=text))
        except Exception as exc:
            # Release the claim so a Celery retry may try again (still bounded by max age).
            await self._alert_log.record(
                evaluation_id, channel=CHANNEL, status=AlertDeliveryStatus.FAILED, error=str(exc)
            )
            raise
        await self._alert_log.record(
            evaluation_id,
            channel=CHANNEL,
            status=AlertDeliveryStatus.SENT,
            message_id=receipt.message_id,
        )
        log.info("alert_sent", evaluation_id=evaluation_id, route=evaluation.route_key)
        return AlertOutcome.SENT

    async def send_event(self, payload: dict[str, Any]) -> AlertOutcome:
        """Render and deliver a system event payload unless it is older than the event max age.

        Stale events (e.g. an ``exchange_down`` retried for minutes after the exchange has
        already recovered) would be misleading, so they are dropped.
        """
        event = event_from_payload(payload)
        emitted_at_ms = payload.get("emitted_at_ms")
        if isinstance(emitted_at_ms, int):
            age_ms = self._clock.now_ms() - emitted_at_ms
            if age_ms > self._event_max_age_ms:
                log.warning("event_expired", kind=event.kind, age_ms=age_ms)
                return AlertOutcome.EXPIRED
        silent = isinstance(event, ExchangeRecovered | EpisodeClosed | WatchdogRecovered)
        await self._notifier.send(OutgoingMessage(text=self._events.render(event), silent=silent))
        log.info("event_sent", kind=event.kind)
        return AlertOutcome.SENT
