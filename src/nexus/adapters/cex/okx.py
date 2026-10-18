"""OKX spot adapter."""

from __future__ import annotations

from typing import ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("okx")
class OkxAdapter(CcxtExchangeAdapter):
    """OKX spot (V5 API; credentials require a passphrase)."""

    name: ClassVar[str] = "okx"
    ccxt_id: ClassVar[str] = "okx"
    static_market_fees: ClassVar[bool] = True
    requires_passphrase: ClassVar[bool] = True
    max_order_book_limit: ClassVar[int] = 400
