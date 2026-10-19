"""MEXC spot adapter."""

from __future__ import annotations

from typing import ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("mexc")
class MexcAdapter(CcxtExchangeAdapter):
    """MEXC spot (V3 API).

    Currency/network data (``capital/config/getall``) is served only to authenticated
    clients; without a read-only key the transfer status stays unknown. Market taker rates
    are symbol-level list rates (zero-fee promotions differ per account), so they are flagged
    as defaults and alert candidates look up the account rate via ``fetchTradingFee``.
    """

    name: ClassVar[str] = "mexc"
    ccxt_id: ClassVar[str] = "mexc"
    static_market_fees: ClassVar[bool] = True
    max_order_book_limit: ClassVar[int] = 1000
