"""Binance spot adapter."""

from __future__ import annotations

from typing import ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("binance")
class BinanceAdapter(CcxtExchangeAdapter):
    """Binance.com spot."""

    name: ClassVar[str] = "binance"
    ccxt_id: ClassVar[str] = "binance"
    static_market_fees: ClassVar[bool] = True
    order_book_limits: ClassVar[tuple[int, ...] | None] = (5, 10, 20, 50, 100, 500, 1000)
