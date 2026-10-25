"""Spread evaluation result types."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nexus.domain.models import ZERO
from nexus.domain.quarantine import route_key


class EvaluationStatus(StrEnum):
    """Outcome of a depth-aware spread evaluation."""

    PROFITABLE = "profitable"
    BELOW_THRESHOLD = "below_threshold"
    NO_SPREAD = "no_spread"
    INSUFFICIENT_DEPTH = "insufficient_depth"
    BELOW_MIN_ORDER = "below_min_order"
    STALE_BOOK = "stale_book"
    SUSPICIOUS_SPREAD = "suspicious_spread"
    MARKET_INACTIVE = "market_inactive"
    TRANSFER_UNAVAILABLE = "transfer_unavailable"
    TRANSFER_UNVERIFIED = "transfer_unverified"
    QUARANTINED = "quarantined"
    """The route is quarantined: stored from tickers only (no books), never alerted."""


class TransferStatus(StrEnum):
    """Whether the asset can be moved from the buy venue to the sell venue."""

    VERIFIED = "verified"
    """A common network with withdraw (source) and deposit (destination) enabled and known fee."""
    UNKNOWN = "unknown"
    """No data (no credentials / asset not listed in metadata / fee or network naming unknown)."""
    UNAVAILABLE = "unavailable"
    """Withdrawals on the source or deposits on the destination are disabled on all networks."""


class LegState(StrEnum):
    """Withdraw (source) or deposit (destination) availability. Never faked: ``UNKNOWN`` when
    the venue does not report it (public-mode venues publish no wallet status)."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TransferQuote:
    """Cheapest known transfer route for the base asset."""

    status: TransferStatus
    network: str | None = None
    fee_base: Decimal = ZERO
    note: str = ""
    contract_verified: bool = False
    """True only when both venues publish the same token contract on the chosen network."""
    withdraw_state: LegState = LegState.UNKNOWN
    """Withdrawals from the buy venue (source), for ``network`` when chosen."""
    deposit_state: LegState = LegState.UNKNOWN
    """Deposits to the sell venue (destination), for ``network`` when chosen."""
    withdraw_min: Decimal | None = None
    deposit_min: Decimal | None = None
    deposit_confirmations: int | None = None
    est_arrival_min: Decimal | None = None
    """Approximate transfer time in minutes (``None`` = unknown); always an estimate."""
    arrival_source: str | None = None
    """``exchange`` (venue estimate) or ``table`` (static per-network table)."""
    busy: bool | None = None
    """Either venue flags the network as congested."""


@dataclass(frozen=True, slots=True)
class ExecutableVolume:
    """Volume the visible order books support for a profitable route.

    ``scanned_*`` is the volume the estimator priced (the reference notional); ``max_*`` is the
    largest volume at which the net profit is still positive (never below the scanned one).
    """

    scanned_base: Decimal
    scanned_quote: Decimal
    max_base: Decimal
    max_quote: Decimal
    max_net_usd: Decimal
    """Net profit at ``max_base`` (the route is net-positive up to here)."""


@dataclass(frozen=True, slots=True)
class SpreadBreakdown:
    """Full cost breakdown of a two-leg arbitrage on the reference notional.

    USD values assume the quote asset is a USD stablecoin (1:1).
    """

    best_ask_buy: Decimal
    best_bid_sell: Decimal
    vwap_buy: Decimal
    vwap_sell: Decimal
    base_bought: Decimal
    """Base amount bought on the buy venue (rounded down to the lot step)."""
    base_received: Decimal
    """Base amount after the buy taker fee."""
    base_sold: Decimal
    """Base amount sold after transfer fee and lot rounding (remainder is treated as lost)."""
    cost_quote: Decimal
    """Quote spent on the buy leg (taker fee is charged in base)."""
    proceeds_quote: Decimal
    """Quote received on the sell leg after the taker fee."""
    gross_spread_pct: Decimal
    net_profit_usd: Decimal
    net_profit_pct: Decimal
    fee_buy_usd: Decimal
    fee_sell_usd: Decimal
    transfer_fee_usd: Decimal
    slippage_usd: Decimal


@dataclass(frozen=True, slots=True)
class SpreadEvaluation:
    """Result of evaluating one route (buy on one venue, sell on another)."""

    symbol: str
    base: str
    quote: str
    buy_exchange: str
    sell_exchange: str
    notional_usd: Decimal
    status: EvaluationStatus
    transfer: TransferQuote
    buy_book_age_ms: int
    sell_book_age_ms: int
    evaluated_at_ms: int
    gross_spread_pct: Decimal | None = None
    breakdown: SpreadBreakdown | None = None
    reason: str = ""
    fees_estimated: bool = False
    """True when a taker fee is a library/fallback estimate rather than exchange data."""
    volume: ExecutableVolume | None = None
    """Computed for ``PROFITABLE`` evaluations only; in memory, not persisted."""

    @property
    def is_alertable(self) -> bool:
        """True if the opportunity passed every filter and threshold."""
        return self.status is EvaluationStatus.PROFITABLE

    @property
    def meets_thresholds(self) -> bool:
        """True if the net profit passed both thresholds, whether or not it is alertable
        (``TRANSFER_UNVERIFIED`` opportunities are priced but never alerted)."""
        return self.status in (EvaluationStatus.PROFITABLE, EvaluationStatus.TRANSFER_UNVERIFIED)

    @property
    def transfer_verified(self) -> bool:
        """False when the transfer path could not be verified (must be shown in alerts)."""
        return self.transfer.status is TransferStatus.VERIFIED

    @property
    def route_key(self) -> str:
        """Stable identifier of the route, used for alert de-duplication."""
        return route_key(self.symbol, self.buy_exchange, self.sell_exchange)
