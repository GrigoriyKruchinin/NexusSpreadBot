"""Daily digest use case (runs in the ``alerts`` worker: database + Telegram only)."""

from __future__ import annotations

import structlog

from nexus.domain.clock import Clock
from nexus.interfaces.notifications import INotifier, OutgoingMessage
from nexus.interfaces.repositories import IDigestRepository
from nexus.notifications.digest import DigestFormatter

log = structlog.get_logger(__name__)

WINDOW_MS = 24 * 3_600_000


class DigestService:
    """Aggregates the last 24 h and sends one Telegram message."""

    def __init__(
        self,
        repository: IDigestRepository,
        notifier: INotifier,
        clock: Clock,
        formatter: DigestFormatter | None = None,
    ) -> None:
        self._repository = repository
        self._notifier = notifier
        self._clock = clock
        self._formatter = formatter or DigestFormatter()

    async def send(self, tz: str) -> str:
        """Build and deliver the digest; returns the Telegram message id."""
        until = self._clock.now_ms()
        data = await self._repository.collect(until - WINDOW_MS, until)
        receipt = await self._notifier.send(OutgoingMessage(text=self._formatter.render(data, tz)))
        log.info(
            "digest_sent",
            episodes=data.episodes.total,
            conditional_venues=list(data.conditional_venues),
            episodes_excl_conditional=data.episodes.total_excl_conditional,
        )
        return receipt.message_id
