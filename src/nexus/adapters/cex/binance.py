"""Binance spot adapter."""

from __future__ import annotations

from typing import ClassVar

from nexus.adapters.cex.binance_public import BinancePublicTransferSource
from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry
from nexus.interfaces.market_data import ITransferStatusSource


@exchange_registry.register("binance")
class BinanceAdapter(CcxtExchangeAdapter):
    """Binance.com spot.

    Without a key, transfer status comes from the public capital config endpoint.
    """

    name: ClassVar[str] = "binance"
    ccxt_id: ClassVar[str] = "binance"
    static_market_fees: ClassVar[bool] = True
    order_book_limits: ClassVar[tuple[int, ...] | None] = (5, 10, 20, 50, 100, 500, 1000)

    def _make_transfer_fallback(self) -> ITransferStatusSource | None:
        return BinancePublicTransferSource(
            timeout_s=self._options.timeout_ms / 1000,
            currency_code=self._rest.safe_currency_code,
            network_code=self._rest.network_id_to_code,
        )
