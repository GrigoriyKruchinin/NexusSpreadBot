"""Persistence interfaces (implemented in :mod:`nexus.persistence.repositories`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from nexus.domain.digest import DigestData
from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.models import MarketInfo
from nexus.domain.quarantine import RouteQuarantine
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import RouteQuote


class AlertDeliveryStatus(StrEnum):
    """Delivery state of an alert."""

    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    """Not sent: over the hourly cap (counted in the "N more suppressed" summary)."""


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
    async def add_evaluations(
        self,
        evaluations: Sequence[SpreadEvaluation],
        episode_ids: Sequence[int | None] | None = None,
    ) -> list[int]:
        """Store evaluations (optionally linked to episodes); returns ids in input order."""

    @abstractmethod
    async def get(self, evaluation_id: int) -> SpreadEvaluation | None:
        """Load one evaluation by id."""


class IEpisodeRepository(ABC):
    """Opportunity episodes (at most one open episode per route)."""

    @abstractmethod
    async def open(self, episode: OpportunityEpisode) -> OpportunityEpisode:
        """Insert a new open episode and return it with its id.

        If the route already has an open episode (e.g. an earlier insert committed but its
        reply was lost), nothing is inserted and the stored open episode is returned.
        """

    @abstractmethod
    async def set_survived_latency(self, episode_id: int, survived: bool) -> None:
        """Record the latency re-check result of an open episode (single-column update)."""

    @abstractmethod
    async def save(self, episodes: Sequence[OpportunityEpisode]) -> None:
        """Persist the mutable state of existing episodes (matched by ``id``).

        A closed episode is never reopened: rows already closed keep their close data.
        """

    @abstractmethod
    async def list_open(self) -> list[OpportunityEpisode]:
        """All episodes that are not closed."""


class IQuarantineRepository(ABC):
    """History of route quarantines (mirror of the shared store, for reports)."""

    @abstractmethod
    async def record_start(self, quarantine: RouteQuarantine) -> None:
        """Store a started quarantine."""

    @abstractmethod
    async def record_lift(self, route_key: str, at_ms: int) -> None:
        """Mark the route's unlifted, unexpired quarantine as lifted early at ``at_ms``."""


@dataclass(frozen=True, slots=True)
class ExchangeMetadataStats:
    """Metadata quality of one exchange after a refresh."""

    exchange: str
    markets: int
    transfer_coverage_pct: int | None


class IMetadataStatsRepository(ABC):
    """Metadata refresh statistics."""

    @abstractmethod
    async def record(self, at_ms: int, stats: Sequence[ExchangeMetadataStats]) -> None:
        """Store the stats of one refresh."""


class IDigestRepository(ABC):
    """Read-only aggregates for the daily digest."""

    @abstractmethod
    async def collect(self, since_ms: int, until_ms: int) -> DigestData:
        """Aggregate the window ``[since_ms, until_ms)``."""


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


@dataclass(frozen=True, slots=True)
class EpisodeMessage:
    """The Telegram message of an episode and what it was last rendered from."""

    episode_id: int
    message_id: str
    evaluation_id: int
    context: dict[str, Any]
    """:class:`~nexus.domain.events.AlertContext` payload of the last rendering."""


@dataclass(frozen=True, slots=True)
class SuppressedSummary:
    """Suppressed NEW alerts of one hourly window and the summary message showing the count."""

    suppressed: int
    message_id: str | None


class IAlertMessageRepository(ABC):
    """Telegram message bookkeeping of the alerts worker (written by it alone)."""

    @abstractmethod
    async def get_episode_message(self, episode_id: int) -> EpisodeMessage | None:
        """The message of an episode, ``None`` if it was never sent (or the episode is gone)."""

    @abstractmethod
    async def save_episode_message(
        self, episode_id: int, *, message_id: str, evaluation_id: int, context: dict[str, Any]
    ) -> None:
        """Store (or replace) the episode's message id and what it was rendered from."""

    @abstractmethod
    async def try_consume(self, window_start_ms: int, limit: int) -> bool:
        """Take one NEW-message slot of the hourly window; ``False`` when ``limit`` is reached."""

    @abstractmethod
    async def refund(self, window_start_ms: int) -> None:
        """Give back a slot taken by :meth:`try_consume` when the send failed."""

    @abstractmethod
    async def record_suppressed(self, window_start_ms: int) -> SuppressedSummary:
        """Count one suppressed alert; returns the window's total and its summary message id."""

    @abstractmethod
    async def set_summary_message(self, window_start_ms: int, message_id: str) -> None:
        """Remember the window's summary message so later suppressions edit it."""


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
        self,
        *,
        snapshots_before: datetime,
        evaluations_before: datetime,
        episodes_before: datetime,
        alerts_sending_before: datetime | None = None,
    ) -> dict[str, int]:
        """Delete rows past their retention window; returns counts per table.

        Also reaps alert deliveries stuck in ``sending`` since ``alerts_sending_before`` (the
        worker died between claim and result): they become ``failed``.
        """
