"""Cross-process coordination interfaces (implemented on Redis / Celery)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nexus.domain.events import AlertContext, SystemEvent
from nexus.domain.quarantine import RouteQuarantine


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
    async def dispatch_opportunity(
        self, evaluation_id: int, context: AlertContext | None = None
    ) -> None:
        """Queue an opportunity alert for a stored evaluation (with its episode context)."""

    @abstractmethod
    async def dispatch_event(self, event: SystemEvent) -> None:
        """Queue a system event notification."""


class IQuarantineStore(ABC):
    """Shared, expiring route quarantines (source of truth for the scanner)."""

    @abstractmethod
    async def add(self, quarantine: RouteQuarantine) -> bool:
        """Start a quarantine; False (no change) if the route is already quarantined."""

    @abstractmethod
    async def active(self) -> dict[str, RouteQuarantine]:
        """Unexpired quarantines by route key."""

    @abstractmethod
    async def lift(self, route_key: str) -> bool:
        """End a quarantine early; True if one was active."""
