"""Gate.io spot adapter."""

from __future__ import annotations

from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("gateio")
class GateIoAdapter(CcxtExchangeAdapter):
    """Gate.io spot (ccxt id ``gate``)."""

    name: ClassVar[str] = "gateio"
    ccxt_id: ClassVar[str] = "gate"
    max_order_book_limit: ClassVar[int] = 100

    async def _key_info_request(self) -> Any:
        """Key policy (A6): signed GET of this key's own permissions (read-only)."""
        return await self._rest.privateAccountGetDetail({})
