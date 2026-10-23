"""Bybit spot adapter."""

from __future__ import annotations

from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("bybit")
class BybitAdapter(CcxtExchangeAdapter):
    """Bybit (unified account, spot category)."""

    name: ClassVar[str] = "bybit"
    ccxt_id: ClassVar[str] = "bybit"
    static_market_fees: ClassVar[bool] = True
    max_order_book_limit: ClassVar[int] = 200
    ws_order_book_limits: ClassVar[tuple[int, ...] | None] = (1, 50, 200, 1000)

    async def _key_info_request(self) -> Any:
        """Key policy (A6): signed GET of this key's own permissions (read-only)."""
        return await self._rest.privateGetV5UserQueryApi({})
