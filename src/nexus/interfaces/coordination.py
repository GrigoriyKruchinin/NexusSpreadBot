"""Cross-process coordination interfaces (implemented on Redis / Celery)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nexus.domain.events import SystemEvent


class ICooldownStore(ABC):
    """Distributed "fire at most once per TTL" gate."""

    @abstractmethod
    async def acquire(self, key: str, ttl_s: int) -> bool:
        """Return True and start the cooldown if ``key`` is not cooling down."""

    @abstractmethod
    async def release(self, key: str) -> None:
        """End a cooldown early (e.g. when the alert could not be queued)."""


class IHeartbeat(ABC):
    """Liveness signal for container healthchecks."""

    @abstractmethod
    async def beat(self, service: str, ttl_s: int) -> None:
        """Record that ``service`` is alive (expires after ``ttl_s``)."""

    @abstractmethod
    async def last_beat_ms(self, service: str) -> int | None:
        """Epoch ms of the last beat, or ``None`` if expired / never."""


class IAlertDispatcher(ABC):
    """Hands alerts to the delivery workers (the scanner never talks to Telegram)."""

    @abstractmethod
    async def dispatch_opportunity(self, evaluation_id: int) -> None:
        """Queue an opportunity alert for a stored evaluation."""

    @abstractmethod
    async def dispatch_event(self, event: SystemEvent) -> None:
        """Queue a system event notification."""
