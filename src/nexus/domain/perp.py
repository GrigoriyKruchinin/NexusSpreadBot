"""Perpetual-swap market-data value objects (read-only, public data; ADR 0009).

All prices, rates and fractions are :class:`~decimal.Decimal`. Fees, rates and the maintenance
margin rate are *fractions* (``Decimal("0.0005")`` == 0.05 %). Funding rates keep the ccxt sign:
a positive rate means longs pay shorts. Order book amounts are converted to **base units**
inside the adapters, so the portfolio never sees contracts; ``contract_size`` and
``amount_step`` only matter for rounding a hedge size to a tradable lot.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nexus.domain.errors import DataValidationError

ZERO = Decimal(0)
MAX_SANE_PERP_FEE = Decimal("0.01")
MAX_SANE_MMR = Decimal("0.5")
MAX_SANE_FUNDING_RATE = Decimal("0.1")
"""A single funding payment above 10 % of notional is treated as a data error."""


@dataclass(frozen=True, slots=True)
class PerpMarket:
    """One linear USDT-margined perpetual swap."""

    exchange: str
    symbol: str
    base: str
    contract_size: Decimal
    """Base-asset units per contract (1 for venues quoting in base units)."""
    amount_step: Decimal
    """Order size increment, in contracts."""
    min_qty: Decimal
    """Minimum order size, in contracts."""
    max_leverage: Decimal | None = None
    mmr: Decimal | None = None
    """Base maintenance margin rate (fraction) when the venue publishes it."""
    taker_fee: Decimal | None = None
    active: bool = True
    delisting: bool = False

    def __post_init__(self) -> None:
        where = f"{self.exchange}:{self.symbol}"
        if self.contract_size <= ZERO:
            msg = f"non-positive contract size for {where}"
            raise DataValidationError(msg)
        if self.amount_step <= ZERO or self.min_qty < ZERO:
            msg = f"invalid lot step/min qty for {where}"
            raise DataValidationError(msg)
        if self.max_leverage is not None and self.max_leverage < 1:
            msg = f"max leverage below 1 for {where}"
            raise DataValidationError(msg)
        if self.mmr is not None and not ZERO <= self.mmr < MAX_SANE_MMR:
            msg = f"implausible maintenance margin rate {self.mmr} for {where}"
            raise DataValidationError(msg)
        if self.taker_fee is not None and not ZERO <= self.taker_fee < MAX_SANE_PERP_FEE:
            msg = f"implausible perp taker fee {self.taker_fee} for {where}"
            raise DataValidationError(msg)

    @property
    def lot_base(self) -> Decimal:
        """Smallest tradable size in base units."""
        return self.amount_step * self.contract_size


@dataclass(frozen=True, slots=True)
class PerpTicker:
    """Top of book of a perp, stamped with the local request-start time (ADR 0005)."""

    exchange: str
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    mark: Decimal | None
    received_at_ms: int

    def __post_init__(self) -> None:
        for price in (self.bid, self.ask, self.mark):
            if price is not None and price <= ZERO:
                msg = f"non-positive price in perp ticker {self.exchange}:{self.symbol}"
                raise DataValidationError(msg)
        if self.bid is not None and self.ask is not None and self.bid >= self.ask:
            msg = f"crossed perp ticker {self.exchange}:{self.symbol}"
            raise DataValidationError(msg)


@dataclass(frozen=True, slots=True)
class FundingInfo:
    """Current funding state of a perp (``rate`` keeps the ccxt sign)."""

    exchange: str
    symbol: str
    rate: Decimal
    next_funding_ms: int | None
    interval_h: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    received_at_ms: int

    def __post_init__(self) -> None:
        where = f"{self.exchange}:{self.symbol}"
        if abs(self.rate) > MAX_SANE_FUNDING_RATE:
            msg = f"implausible funding rate {self.rate} for {where}"
            raise DataValidationError(msg)
        if self.interval_h is not None and self.interval_h <= ZERO:
            msg = f"non-positive funding interval for {where}"
            raise DataValidationError(msg)
        for price in (self.mark_price, self.index_price):
            if price is not None and price <= ZERO:
                msg = f"non-positive mark/index price for {where}"
                raise DataValidationError(msg)


@dataclass(frozen=True, slots=True)
class MarkKline:
    """One mark-price candle (1 m); ``open_ms`` is the candle start."""

    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if any(p <= ZERO for p in prices) or self.low > self.high:
            msg = f"invalid mark kline at {self.open_ms}"
            raise DataValidationError(msg)
        if not self.low <= min(self.open, self.close) or self.high < max(self.open, self.close):
            msg = f"mark kline OHLC inconsistent at {self.open_ms}"
            raise DataValidationError(msg)


@dataclass(frozen=True, slots=True)
class FundingPayment:
    """A settled funding rate (history)."""

    symbol: str
    funding_time_ms: int
    rate: Decimal

    def __post_init__(self) -> None:
        if abs(self.rate) > MAX_SANE_FUNDING_RATE:
            msg = f"implausible settled funding rate {self.rate} for {self.symbol}"
            raise DataValidationError(msg)


@dataclass(frozen=True, slots=True)
class LeverageTier:
    """One maintenance-margin tier: positions with notional in ``[min, max)`` USDT."""

    min_notional: Decimal
    max_notional: Decimal | None
    max_leverage: Decimal
    mmr: Decimal

    def __post_init__(self) -> None:
        if self.min_notional < ZERO or (
            self.max_notional is not None and self.max_notional <= self.min_notional
        ):
            msg = "invalid leverage tier bounds"
            raise DataValidationError(msg)
        if self.max_leverage < 1 or not ZERO <= self.mmr < MAX_SANE_MMR:
            msg = "invalid leverage tier leverage/mmr"
            raise DataValidationError(msg)
