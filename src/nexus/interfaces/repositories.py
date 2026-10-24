"""Persistence interfaces (implemented in :mod:`nexus.persistence.repositories`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from nexus.domain.digest import DigestData
from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.models import MarketInfo
from nexus.domain.quarantine import RouteQuarantine
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import RouteQuote
from nexus.simulation.portfolio import Rebalance, Seed, TradeOutcome


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
class PaperHolding:
    """One venue of a paper balance snapshot."""

    exchange: str
    asset: str
    amount: Decimal
    seed: Seed | None
    price_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class PaperState:
    """Everything needed to resume the paper portfolio after a restart."""

    holdings: list[PaperHolding]
    in_flight: list[Rebalance]
    realized: Decimal
    rebalance_costs: Decimal


@dataclass(frozen=True, slots=True)
class RunDefinition:
    """What a paper portfolio run was configured with (``config_hash`` identifies it)."""

    venues: tuple[str, ...]
    capital_usd: Decimal
    config_hash: str


@dataclass(frozen=True, slots=True)
class PortfolioRun:
    """One run of a named portfolio: a fresh capital start under one definition."""

    portfolio_id: str
    run_id: int
    started_at_ms: int
    definition: RunDefinition
    created: bool = False
    """True when this call started the run (fresh capital); False = resumed the stored one."""
    previous_hash: str | None = None
    """Definition hash of the run this one replaced (``None`` = first run of the name)."""


@dataclass(frozen=True, slots=True)
class CapStatsDelta:
    """Per-set, per-hour cap-binding counters to add to the stored aggregate."""

    portfolio_id: str
    hour_ms: int
    sweeps: int = 0
    sweeps_cap_bound: int = 0
    dropped_routes: int = 0
    alerts_cap_excluded: int = 0


class IPaperRepository(ABC):
    """Paper trading records."""

    @abstractmethod
    async def ensure_run(
        self, portfolio_id: str, definition: RunDefinition, now_ms: int
    ) -> PortfolioRun:
        """Resume the latest run of the portfolio if its definition is identical, else start a
        NEW run (``created=True``; the old rows stay but are never restored). The run's
        ``started_at`` is the portfolio's ``since``; it lives outside the purged snapshots."""

    @abstractmethod
    async def add_cap_stats(self, deltas: Sequence[CapStatsDelta]) -> None:
        """Add the counters to the stored hourly aggregates (upsert, additive)."""

    @abstractmethod
    async def commit(
        self,
        *,
        portfolio_id: str,
        at_ms: int,
        trades: Sequence[tuple[TradeOutcome, int | None]],
        rebalances: Sequence[Rebalance],
        holdings: Sequence[PaperHolding],
    ) -> list[Rebalance]:
        """Atomically store trades (with episode ids), rebalance inserts/updates and a full
        balance snapshot of one portfolio; returns the rebalances with their ids."""

    @abstractmethod
    async def load_state(self, portfolio_id: str, since_ms: int = 0) -> PaperState | None:
        """Latest snapshot, in-flight rebalances and running totals of one portfolio, counting
        only rows at or after ``since_ms`` (the current run; ``None`` = nothing to resume)."""


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
        """Aggregate the window ``[since_ms, until_ms)`` (portfolio values: latest state)."""


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
        self,
        *,
        snapshots_before: datetime,
        evaluations_before: datetime,
        episodes_before: datetime,
    ) -> dict[str, int]:
        """Delete rows past their retention window; returns counts per table.

        Paper trades and transfers are kept (portfolio totals are summed from them), and the
        latest paper balance snapshot set always survives.
        """
