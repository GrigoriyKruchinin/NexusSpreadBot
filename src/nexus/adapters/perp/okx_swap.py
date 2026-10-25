"""OKX linear USDT swap market data (public, no credentials).

Endpoints (ccxt method -> REST path, all GET). Limits are the working numbers from the OKX v5 docs
(per IP and endpoint) and are not re-measured here:

* ``load_markets``: ``/api/v5/public/instruments?instType=SWAP`` (ctVal, lotSz, lever, expTime).
* ``fetch_tickers``: ``/api/v5/market/tickers?instType=SWAP``, 20 requests / 2 s.
* ``fetch_order_book``: ``/api/v5/market/books``, 40 requests / 2 s, up to 400 levels, in contracts.
* ``fetch_funding_rate``: ``/api/v5/public/funding-rate?instId=``, 20 requests / 2 s. One call per
  instrument, so ``fetch_funding(None)`` returns nothing; callers pass the candidates, cache 60 s.
* ``fetch_mark_prices``: ``/api/v5/public/mark-price?instType=SWAP``, 10 requests / 2 s, bulk.
* ``fetch_mark_ohlcv``: ``/api/v5/market/mark-price-candles``, 100 rows per call (15 for 24 h).
* ``fetch_funding_rate_history``: ``/api/v5/public/funding-rate-history``, 100 rows per call.
* ``fetch_market_leverage_tiers``: ``/api/v5/public/position-tiers``. Tier bounds are in the venue's
  own unit; HT uses the first tier's maintenance margin rate only.

The ccxt client throttles itself (``enableRateLimit``); a 429 raises ``ExchangeRateLimitError`` and
the feed pauses this venue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any, ClassVar

from nexus.adapters.perp.ccxt_perp import CcxtPerpAdapter
from nexus.adapters.perp.registry import perp_registry
from nexus.domain.errors import ExchangeDataError


@perp_registry.register("okx")
class OkxSwapAdapter(CcxtPerpAdapter):
    """OKX USDT-margined perpetual swaps."""

    name: ClassVar[str] = "okx"
    ccxt_id: ClassVar[str] = "okx"
    ccxt_options: ClassVar[Mapping[str, Any]] = {
        "defaultType": "swap",
        "fetchMarkets": {"types": ["swap"]},
        "fetchCurrencies": False,
    }
    max_order_book_limit: ClassVar[int] = 400

    def _is_delisting(self, info: Mapping[str, Any]) -> bool:
        return bool(str(info.get("expTime") or "").strip())

    async def _fetch_funding_rates(self, symbols: Sequence[str] | None) -> Mapping[str, Any]:
        """One request per instrument (OKX has no bulk funding endpoint)."""
        if not symbols:
            return {}
        result: dict[str, Any] = {}
        for symbol in symbols:
            try:
                result[symbol] = await self._call(
                    f"fetch_funding_rate {symbol}", partial(self._rest.fetch_funding_rate, symbol)
                )
            except ExchangeDataError as exc:
                self._log.info("funding_unavailable", symbol=symbol, error=str(exc))
        return result
