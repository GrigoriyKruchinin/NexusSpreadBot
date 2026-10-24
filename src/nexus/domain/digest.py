"""Daily digest data (aggregated from the database, rendered by the notifier)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from nexus.domain.models import ZERO

HUNDRED = Decimal(100)
HOUR_MS = 3_600_000


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
class PaperStats:
    """Paper trading: window activity and the portfolio since start."""

    trades: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    realized_usd: Decimal = ZERO
    """Realized arbitrage profit in the window."""
    rebalance_usd: Decimal = ZERO
    """Virtual transfer fees in the window."""
    rebalances: int = 0
    blocked_rebalances: int = 0
    capital_usd: Decimal = ZERO
    equity_usd: Decimal = ZERO
    realized_total_usd: Decimal = ZERO
    rebalance_total_usd: Decimal = ZERO
    realized_total_excl_conditional_usd: Decimal | None = None
    """Since start, trades not touching a conditional venue (no equity/MTM); ``None`` = unknown."""
    rebalance_total_excl_conditional_usd: Decimal | None = None

    @property
    def total_pnl_usd(self) -> Decimal:
        """Since start: equity minus capital."""
        return self.equity_usd - self.capital_usd

    @property
    def mark_to_market_usd(self) -> Decimal:
        """Since start: price effect on inventory (total minus trading and transfers)."""
        return self.total_pnl_usd - self.realized_total_usd + self.rebalance_total_usd

    @property
    def hedged_pnl_usd(self) -> Decimal:
        """Since start, as if inventory price risk were hedged: arbitrage minus transfers."""
        return self.realized_total_usd - self.rebalance_total_usd

    @property
    def hedged_pnl_excl_conditional_usd(self) -> Decimal | None:
        """Hedged P&L from rows not touching any conditional venue; ``None`` if not computed."""
        realized = self.realized_total_excl_conditional_usd
        rebalance = self.rebalance_total_excl_conditional_usd
        if realized is None or rebalance is None:
            return None
        return realized - rebalance

    @property
    def hedged_roc_pct(self) -> Decimal | None:
        """Hedged P&L over capital, percent."""
        if self.capital_usd <= ZERO:
            return None
        return self.hedged_pnl_usd / self.capital_usd * HUNDRED

    @property
    def roc_pct(self) -> Decimal | None:
        """Since start: return on capital, percent."""
        if self.capital_usd <= ZERO:
            return None
        return self.total_pnl_usd / self.capital_usd * HUNDRED


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    """One shadow portfolio (venue set) since its first record - never backfilled."""

    portfolio_id: str
    since_ms: int
    trades: int
    hedged_pnl_usd: Decimal
    """Realized arbitrage minus virtual transfer fees since ``since_ms``."""
    restarted: bool = False
    """The run began inside the digest window although an earlier run of this set existed
    (its definition changed): the set restarted with full capital and this new ``since``."""


@dataclass(frozen=True, slots=True)
class SetCoverage:
    """How continuously the scanner swept one shadow portfolio (venue set) in the window.

    Only complete hours after the set's first record are judged; the partial first and last
    hours are skipped, so a set added today is never blamed for the time before it existed.
    """

    portfolio_id: str
    hours_expected: int
    hours_gap: int
    """Hours with fewer sweeps than the configured minimum (includes hours with no row)."""
    downtime_min: int
    """Missing share of the minimum sweep count per hour, as minutes (60 = hour fully dark)."""


def compute_set_coverage(
    sweeps_by_hour: Mapping[str, Mapping[int, int]],
    first_seen_ms: Mapping[str, int],
    window_start_ms: int,
    window_end_ms: int,
    min_sweeps_per_hour: int,
) -> tuple[SetCoverage, ...]:
    """Per-set gap accounting from ``paper_cap_stats.sweeps`` (hour start ms -> sweeps)."""
    first_full = -(-window_start_ms // HOUR_MS) * HOUR_MS  # ceil to a whole hour
    last_end = window_end_ms - window_end_ms % HOUR_MS
    result: list[SetCoverage] = []
    for pid, first_seen in sorted(first_seen_ms.items()):
        start = max(first_full, first_seen - first_seen % HOUR_MS + HOUR_MS)
        hours = range(start, last_end, HOUR_MS)
        counts = sweeps_by_hour.get(pid, {})
        gaps = [h for h in hours if counts.get(h, 0) < min_sweeps_per_hour]
        missing = sum(round(60 * (1 - counts.get(h, 0) / min_sweeps_per_hour)) for h in gaps)
        result.append(SetCoverage(pid, len(hours), len(gaps), missing))
    result.sort(key=lambda c: (c.portfolio_id != "all", c.portfolio_id))
    return tuple(result)


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
    paper: PaperStats | None
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
    portfolios: tuple[PortfolioSummary, ...] = ()
    """Shadow portfolios that have records (``all`` first)."""
    coverage: tuple[SetCoverage, ...] = ()
    """Per-set scanner coverage / downtime in the window (empty = nothing recorded)."""
