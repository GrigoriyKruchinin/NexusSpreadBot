"""KuCoin spot adapter."""

from __future__ import annotations

from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter
from nexus.adapters.registry import exchange_registry


@exchange_registry.register("kucoin")
class KucoinAdapter(CcxtExchangeAdapter):
    """KuCoin spot (credentials require a passphrase; book depth is 20 or 100)."""

    name: ClassVar[str] = "kucoin"
    ccxt_id: ClassVar[str] = "kucoin"
    requires_passphrase: ClassVar[bool] = True
    order_book_limits: ClassVar[tuple[int, ...] | None] = (20, 100)
    ws_public_post_paths: ClassVar[frozenset[str]] = frozenset({"/api/v1/bullet-public"})
    """KuCoin issues WebSocket tokens via POST (public, no credentials involved)."""

    async def _key_info_request(self) -> Any:
        """Key policy (A6): signed GET of this key's own permissions (read-only)."""
        return await self._rest.privateGetUserApiKey({})
