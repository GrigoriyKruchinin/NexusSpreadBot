"""Largest route volume that stays net-positive on the visible order books.

Uses the same cost model as :class:`~nexus.engine.estimator.NetSpreadEstimator` (buy fee in
base, fixed transfer fee plus chain tax, lot rounding on both legs, sell fee in quote) for an
arbitrary base amount. Net profit is concave in the volume (asks get dearer, bids cheaper, the
transfer fee is fixed), so the net-positive volumes form one interval and a bisection finds
its upper end. Pure and read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nexus.domain.models import ZERO, MarketInfo, OrderBook
from nexus.domain.spread import ExecutableVolume
from nexus.engine.depth import buy_base, floor_to_step, sell_base

ONE = Decimal(1)
HUNDRED = Decimal(100)
BISECTION_STEPS = 48


@dataclass(frozen=True, slots=True)
class VolumeModel:
    """Everything the net-profit function of one route needs."""

    buy_book: OrderBook
    sell_book: OrderBook
    buy_market: MarketInfo
    sell_market: MarketInfo
    transfer_fee_base: Decimal
    """Fixed withdrawal fee in base units (zero when transfer cost is not modelled)."""
    transfer_tax_pct: Decimal

    def net(self, base_bought: Decimal) -> tuple[Decimal, Decimal] | None:
        """``(cost_quote, net_usd)`` for buying ``base_bought``; ``None`` if depth is short."""
        if base_bought <= ZERO:
            return None
        buy_fill = buy_base(self.buy_book.asks, base_bought)
        if buy_fill is None:
            return None
        received = base_bought * (ONE - self.buy_market.taker_fee)
        fee = self.transfer_fee_base + (received - self.transfer_fee_base) * (
            self.transfer_tax_pct / HUNDRED
        )
        sold = floor_to_step(received - fee, self.sell_market.amount_step)
        if sold <= ZERO:
            return None
        sell_fill = sell_base(self.sell_book.bids, sold)
        if sell_fill is None:
            return None
        proceeds = sell_fill.quote_amount * (ONE - self.sell_market.taker_fee)
        return buy_fill.quote_amount, proceeds - buy_fill.quote_amount

    def max_volume(self, scanned_base: Decimal) -> ExecutableVolume | None:
        """Volume bounds around the scanned amount; ``None`` if it is not net-positive."""
        scanned = self.net(scanned_base)
        if scanned is None or scanned[1] <= ZERO:
            return None
        step = self.buy_market.amount_step
        depth = sum((level.amount for level in self.buy_book.asks), ZERO)
        high = floor_to_step(depth, step)
        best_base, best = scanned_base, scanned
        top = self.net(high) if high > scanned_base else None
        if top is not None and top[1] > ZERO:
            best_base, best = high, top
        elif high > scanned_base:
            low = scanned_base
            for _ in range(BISECTION_STEPS):
                mid = floor_to_step((low + high) / 2, step)
                if mid <= low or mid >= high:
                    break
                result = self.net(mid)
                if result is not None and result[1] > ZERO:
                    low, best_base, best = mid, mid, result
                else:
                    high = mid
        return ExecutableVolume(
            scanned_base=scanned_base,
            scanned_quote=scanned[0],
            max_base=best_base,
            max_quote=best[0],
            max_net_usd=best[1],
        )
