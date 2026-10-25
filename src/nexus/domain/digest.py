"""Daily digest data (aggregated from the database, rendered by the notifier)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EpisodeSummary:
    """One route of the top-episodes list."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    peak_net_usd: Decimal
    peak_net_pct: Decimal
    duration_s: int
    survived_latency: bool | None


@dataclass(frozen=True, slots=True)
class EpisodeStats:
    """Opportunity episodes opened in the window."""

    total: int = 0
    verified: int = 0
    unverified: int = 0
    quarantined: int = 0
    survived_latency: int = 0
    latency_checked: int = 0
    median_duration_s: int | None = None
    max_duration_s: int | None = None
    top: tuple[EpisodeSummary, ...] = ()
    total_excl_conditional: int | None = None
    """Episodes on routes touching no conditional venue (``None`` = not computed)."""


@dataclass(frozen=True, slots=True)
class QuarantineSummary:
    """A quarantine started in the window."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    reason: str


@dataclass(frozen=True, slots=True)
class DigestData:
    """Everything the daily digest shows."""

    window_start_ms: int
    window_end_ms: int
    episodes: EpisodeStats
    quarantines: tuple[QuarantineSummary, ...]
    active_quarantines: int
    uptime_pct: dict[str, int | None]
    """Share of successful exchange calls in the window (``None`` = no calls recorded)."""
    coverage_pct: dict[str, int | None]
    """Latest transfer-status coverage per exchange."""
    conditional_venues: tuple[str, ...] = ()
    """Configured conditional venues (lowercase ids)."""
    unverified_evaluations: int = 0
    """Qualifying evaluations that were not alerted for lack of a verified transfer path."""
