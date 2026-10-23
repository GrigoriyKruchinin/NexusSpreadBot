"""Binance spot adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

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
    ccxt_options: ClassVar[Mapping[str, Any]] = {
        "defaultType": "spot",
        # Signed calls fail with -1021 when the host clock drifts (WSL after sleep).
        "adjustForTimeDifference": True,
        "recvWindow": 10_000,
    }
    order_book_limits: ClassVar[tuple[int, ...] | None] = (5, 10, 20, 50, 100, 500, 1000)

    def _make_transfer_fallback(self) -> ITransferStatusSource | None:
        return BinancePublicTransferSource(
            timeout_s=self._options.timeout_ms / 1000,
            currency_code=self._rest.safe_currency_code,
            network_code=self._rest.network_id_to_code,
        )

    async def _key_info_request(self) -> Any:
        """Key policy (A6): signed GET of this key's own permissions (read-only)."""
        return await self._rest.sapiGetAccountApiRestrictions({})
