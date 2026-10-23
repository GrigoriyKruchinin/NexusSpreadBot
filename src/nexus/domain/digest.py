"""Daily digest data (aggregated from the database, rendered by the notifier)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nexus.domain.models import ZERO

HUNDRED = Decimal(100)


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
