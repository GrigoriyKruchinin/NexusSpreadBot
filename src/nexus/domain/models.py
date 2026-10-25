"""Core market-data value objects.

All prices, amounts and fees are :class:`~decimal.Decimal`. Fees are stored as *fractions*
(``Decimal("0.001")`` == 0.1 %). Amounts are always in the **base** asset unless the name
says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from nexus.domain.errors import DataValidationError, InvalidOrderBookError

ZERO = Decimal(0)
MAX_SANE_TAKER_FEE = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class PriceLevel:
    """A single order book level."""

    price: Decimal
    amount: Decimal


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Order book snapshot.

    Bids are sorted best-first (descending price), asks best-first (ascending price).
    ``timestamp_ms`` is the exchange timestamp when available, otherwise the local receive
    time; ``received_at_ms`` is always the local receive time.
    """

    exchange: str
    symbol: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    timestamp_ms: int
    received_at_ms: int
    streamed: bool = False
    """True for a WebSocket-maintained book (incrementally updated, may drift out of sync)."""

    def __post_init__(self) -> None:
        self._validate_side(self.bids, descending=True)
        self._validate_side(self.asks, descending=False)
        if self.bids and self.asks and self.bids[0].price >= self.asks[0].price:
            msg = (
                f"crossed order book {self.exchange}:{self.symbol} "
                f"bid={self.bids[0].price} ask={self.asks[0].price}"
            )
            raise InvalidOrderBookError(msg)

    def _validate_side(self, levels: tuple[PriceLevel, ...], *, descending: bool) -> None:
        previous: Decimal | None = None
        for level in levels:
            if level.price <= ZERO or level.amount <= ZERO:
                msg = f"non-positive level in {self.exchange}:{self.symbol}: {level}"
                raise InvalidOrderBookError(msg)
            if previous is not None and (
                (descending and level.price >= previous)
                or (not descending and level.price <= previous)
            ):
                msg = f"unsorted levels in {self.exchange}:{self.symbol}"
                raise InvalidOrderBookError(msg)
            previous = level.price

    @property
    def best_bid(self) -> Decimal | None:
        """Highest bid price, if any."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Lowest ask price, if any."""
        return self.asks[0].price if self.asks else None

    def age_ms(self, now_ms: int) -> int:
        """Age of the snapshot relative to ``now_ms`` (older of exchange/receive time)."""
        return now_ms - min(self.timestamp_ms, self.received_at_ms)


@dataclass(frozen=True, slots=True)
class Ticker:
    """Top-of-book ticker used for the cheap candidate pre-filter."""

    exchange: str
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    quote_volume_24h: Decimal | None
    timestamp_ms: int | None
    """Exchange timestamp if reported. Not a freshness signal: depth checks use book age."""


@dataclass(frozen=True, slots=True)
class MarketInfo:
    """Static-ish market metadata for one symbol on one exchange."""

    exchange: str
    symbol: str
    base: str
    quote: str
    taker_fee: Decimal
    amount_step: Decimal | None = None
    min_amount: Decimal | None = None
    min_cost: Decimal | None = None
    active: bool = True
    taker_fee_is_default: bool = False
    """True when the exchange did not report a fee and a conservative fallback is used."""

    def __post_init__(self) -> None:
        if not ZERO <= self.taker_fee < MAX_SANE_TAKER_FEE:
            msg = f"implausible taker fee {self.taker_fee} for {self.exchange}:{self.symbol}"
            raise DataValidationError(msg)


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    """Deposit/withdrawal availability of one asset on one network.

    ``None`` flags mean the exchange did not report the status (unknown, not disabled).
    """

    network: str
    withdraw_enabled: bool | None
    deposit_enabled: bool | None
    withdraw_fee: Decimal | None
    contract: str | None = None
    """Token contract address on this network, when published (detects ticker collisions)."""
    withdraw_min: Decimal | None = None
    """Minimum withdrawal size in the asset (``None`` = not published)."""
    deposit_min: Decimal | None = None
    """Minimum deposit size in the asset (deposits below it are not credited)."""
    deposit_confirmations: int | None = None
    """Block confirmations before a deposit is credited."""
    est_arrival_min: Decimal | None = None
    """Exchange-estimated arrival time in minutes."""
    busy: bool | None = None
    """Venue flags the network as congested/busy."""


@dataclass(frozen=True, slots=True)
class AssetTransferInfo:
    """Transfer capabilities of one asset on one exchange."""

    exchange: str
    asset: str
    networks: tuple[NetworkInfo, ...] = field(default_factory=tuple)
    withdraw_enabled: bool | None = None
    """Currency-level withdrawal flag (``False`` disables every network)."""
    deposit_enabled: bool | None = None
    """Currency-level deposit flag (``False`` disables every network)."""
