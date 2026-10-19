"""Bitget spot adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter, to_decimal
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("bitget")
class BitgetAdapter(CcxtExchangeAdapter):
    """Bitget spot (V2 API; credentials require a passphrase).

    ccxt's non-UTA ``fetchTradingFees`` returns the public symbol list rates, not the
    account tier, so the bulk call is skipped and markets are flagged as default-fee; alert
    candidates look up the account rate via ``fetchTradingFee`` (``common/trade-rate``).
    """

    name: ClassVar[str] = "bitget"
    ccxt_id: ClassVar[str] = "bitget"
    requires_passphrase: ClassVar[bool] = True
    static_market_fees: ClassVar[bool] = True
    bulk_account_fees: ClassVar[bool] = False
    max_order_book_limit: ClassVar[int] = 150
    ws_order_book_limits: ClassVar[tuple[int, ...] | None] = (1, 5, 15, 150)
    """Fixed-depth public channels books1/5/15; any other limit uses the full ``books`` feed."""

    def _has_unmodelled_withdraw_fee(self, network: Mapping[str, Any]) -> bool:
        """Bitget's ``extraWithdrawFee`` is a percentage on top of ``withdrawFee`` (e.g. burn
        tokens); ccxt drops it, so such networks are treated as fee-unknown.
        """
        info = network.get("info")
        if not isinstance(info, Mapping):
            return False
        raw = info.get("extraWithdrawFee")
        if raw is None or raw == "":
            return False
        extra = to_decimal(raw)
        return extra is None or extra != 0  # unparsable counts as unmodelled
