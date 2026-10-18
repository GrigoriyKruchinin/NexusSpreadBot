"""Alert delivery use case (runs in the ``alerts`` worker)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import structlog

from nexus.domain.clock import Clock
from nexus.domain.errors import NotificationError
from nexus.domain.events import ExchangeRecovered, event_from_payload
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
        opportunity_formatter: OpportunityFormatter | None = None,
        event_formatter: SystemEventFormatter | None = None,
    ) -> None:
        self._evaluations = evaluations
        self._alert_log = alert_log
        self._notifier = notifier
        self._clock = clock
        self._max_age_ms = max_age_s * 1000
        self._opportunity = opportunity_formatter or OpportunityFormatter()
        self._events = event_formatter or SystemEventFormatter()

    async def send_opportunity(self, evaluation_id: int) -> AlertOutcome:
        """Deliver the alert for ``evaluation_id`` unless already sent, stale or invalid."""
        if await self._alert_log.was_sent(evaluation_id):
            return AlertOutcome.DUPLICATE
        evaluation = await self._evaluations.get(evaluation_id)
        if evaluation is None:
            return AlertOutcome.MISSING
        if not evaluation.is_alertable:
            return AlertOutcome.NOT_ALERTABLE
        age_ms = self._clock.now_ms() - evaluation.evaluated_at_ms
        if age_ms > self._max_age_ms:
            await self._alert_log.record(
                evaluation_id,
                channel=CHANNEL,
                status=AlertDeliveryStatus.FAILED,
                error=f"expired: alert was {age_ms // 1000}s old",
            )
            log.warning("alert_expired", evaluation_id=evaluation_id, age_ms=age_ms)
            return AlertOutcome.EXPIRED
        text = self._opportunity.render(evaluation)
        try:
            receipt = await self._notifier.send(OutgoingMessage(text=text))
        except NotificationError as exc:
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
        """Render and deliver a system event payload."""
        event = event_from_payload(payload)
        silent = isinstance(event, ExchangeRecovered)
        await self._notifier.send(OutgoingMessage(text=self._events.render(event), silent=silent))
        log.info("event_sent", kind=event.kind)
        return AlertOutcome.SENT
