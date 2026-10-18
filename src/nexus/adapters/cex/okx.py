"""OKX spot adapter."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter, to_decimal
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("okx")
class OkxAdapter(CcxtExchangeAdapter):
    """OKX spot (V5 API; credentials require a passphrase)."""

    name: ClassVar[str] = "okx"
    ccxt_id: ClassVar[str] = "okx"
    static_market_fees: ClassVar[bool] = True
    requires_passphrase: ClassVar[bool] = True
    max_order_book_limit: ClassVar[int] = 400
    ws_order_book_limits: ClassVar[tuple[int, ...] | None] = (1, 5, 400)
    """Public WS channels: bbo-tbt, books5, books (books50-l2-tbt needs a VIP4+ login)."""

    def _taker_from_fee_entry(self, symbol: str, raw: Mapping[str, Any]) -> Decimal | None:
        """OKX reports USDT-pair (``taker``) and USDC/crypto-pair (``takerUSDC``) rates.

        ccxt maps only ``taker``; for non-USDT quotes use the larger (more conservative) of
        both. OKX encodes fees as negative numbers (rebates positive).
        """
        taker = to_decimal(raw.get("taker"))
        if symbol.endswith("/USDT") or taker is None:
            return taker
        info = raw.get("info")
        usdc_raw = to_decimal(info.get("takerUSDC")) if isinstance(info, Mapping) else None
        if usdc_raw is None:
            return None  # cannot tell the applicable rate: keep the default fee
        return max(taker, -usdc_raw)
