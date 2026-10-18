"""Order book depth walking (VWAP execution simulation)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, localcontext

from nexus.domain.models import ZERO, PriceLevel


@dataclass(frozen=True, slots=True)
class Fill:
    """Simulated taker fill across one or more levels."""

    base_amount: Decimal
    quote_amount: Decimal
    levels_used: int

    @property
    def vwap(self) -> Decimal:
        """Volume-weighted average execution price."""
        return self.quote_amount / self.base_amount


def floor_to_step(value: Decimal, step: Decimal | None) -> Decimal:
    """Round ``value`` down to a multiple of ``step`` (no-op when ``step`` is None/zero)."""
    if step is None or step <= ZERO:
        return value
    with localcontext() as ctx:
        ctx.prec = 60  # avoid DivisionImpossible for tiny steps on huge amounts
        units = (value / step).to_integral_value(rounding=ROUND_FLOOR)
        return units * step


def max_base_for_quote(asks: Sequence[PriceLevel], quote_budget: Decimal) -> Decimal | None:
    """Base amount obtainable by spending ``quote_budget`` on ``asks``.

    Returns ``None`` if the visible depth cannot absorb the full budget.
    """
    if quote_budget <= ZERO:
        return ZERO
    remaining = quote_budget
    base = ZERO
    for level in asks:
        level_quote = level.price * level.amount
        if level_quote >= remaining:
            return base + remaining / level.price
        base += level.amount
        remaining -= level_quote
    return None


def _walk(levels: Sequence[PriceLevel], base_amount: Decimal) -> Fill | None:
    if base_amount <= ZERO:
        return Fill(ZERO, ZERO, 0)
    remaining = base_amount
    quote = ZERO
    for index, level in enumerate(levels, start=1):
        take = min(remaining, level.amount)
        quote += take * level.price
        remaining -= take
        if remaining <= ZERO:
            return Fill(base_amount, quote, index)
    return None


def buy_base(asks: Sequence[PriceLevel], base_amount: Decimal) -> Fill | None:
    """Simulate a taker buy of ``base_amount``; ``None`` if depth is insufficient."""
    return _walk(asks, base_amount)


def sell_base(bids: Sequence[PriceLevel], base_amount: Decimal) -> Fill | None:
    """Simulate a taker sell of ``base_amount``; ``None`` if depth is insufficient."""
    return _walk(bids, base_amount)
