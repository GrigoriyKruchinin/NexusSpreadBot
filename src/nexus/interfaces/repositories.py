"""Persistence interfaces (implemented in :mod:`nexus.persistence.repositories`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from nexus.domain.models import MarketInfo
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import RouteQuote


class AlertDeliveryStatus(StrEnum):
    """Delivery state of an alert."""

    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class IMarketRepository(ABC):
    """Market metadata storage."""

    @abstractmethod
    async def upsert_markets(self, markets: Sequence[MarketInfo]) -> int:
        """Insert or update markets; returns the number of rows written."""


class ISnapshotRepository(ABC):
    """Top-of-book spread samples."""

    @abstractmethod
    async def add_snapshots(self, captured_at: datetime, routes: Sequence[RouteQuote]) -> int:
        """Store route quotes captured at ``captured_at``."""


class IEvaluationRepository(ABC):
    """Depth-aware spread evaluations."""

    @abstractmethod
    async def add_evaluations(self, evaluations: Sequence[SpreadEvaluation]) -> list[int]:
        """Store evaluations; returns their ids in input order."""

    @abstractmethod
    async def get(self, evaluation_id: int) -> SpreadEvaluation | None:
        """Load one evaluation by id."""


class IAlertLogRepository(ABC):
    """Alert delivery log (idempotency)."""

    @abstractmethod
    async def claim(self, evaluation_id: int, *, channel: str) -> bool:
        """Atomically mark ``evaluation_id`` as being sent.

        Returns ``True`` only for the first claim, or when the previous attempt ``FAILED``.
        A ``SENDING`` or ``SENT`` record is never re-claimed: a worker that died between the
        send and the final ``record`` call leaves ``SENDING`` behind, and the alert is then
        dropped rather than risk a duplicate message (at-most-once delivery).
        """

    @abstractmethod
    async def record(
        self,
        evaluation_id: int,
        *,
        channel: str,
        status: AlertDeliveryStatus,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Insert or update the delivery record of ``evaluation_id``."""


class IExchangeHealthRepository(ABC):
    """Exchange call outcomes."""

    @abstractmethod
    async def record(
        self,
        exchange: str,
        operation: str,
        *,
        ok: bool,
        latency_ms: int | None,
        error: str | None = None,
    ) -> None:
        """Store one call outcome."""


class IRetentionRepository(ABC):
    """Housekeeping."""

    @abstractmethod
    async def purge(
        self, *, snapshots_before: datetime, evaluations_before: datetime
    ) -> dict[str, int]:
        """Delete old snapshots and non-profitable evaluations; returns counts per table."""
