"""KuCoin futures (linear USDT) market data (public, no credentials).

Host ``api-futures.kucoin.com`` (ccxt ``kucoinfutures``). Limits are the working numbers from the
KuCoin docs (public futures pool, about 2000 weight / 30 s per IP) and are not re-measured here:

* ``load_markets``: ``/api/v1/contracts/active`` (multiplier, lotSize, maxLeverage, maintainMargin,
  status, expireDate, markPrice, indexPrice, funding fields), weight about 10.
* ``fetch_bids_asks``: ``/api/v1/allTickers`` (bulk best bid/ask), weight about 5. The unified
  ``fetch_tickers`` (contracts/active) carries no bid/ask, so it is used only for mark/index.
* ``fetch_order_book``: ``/api/v1/level2/depth20`` or ``depth100`` (contracts), weight about 5.
* ``fetch_funding_rates``: bulk current rate and funding time; mark/index come from the
  ``contracts/active`` ticker call. Funding interval from the unified ``interval`` ("8h").
* ``fetch_mark_ohlcv``: ccxt routes mark candles to the unified-account kline endpoint (public).
  It returns at most 200 rows per call, the newest 200 of the requested window, so the page size
  must be 200 (8 calls for 24 h). Its column order differs from the documented futures klines:
  only ``high``/``low`` (max/min of the four price columns, what the liquidation check needs) are
  reliable; ``open``/``close`` follow the observed layout (open, low, close, high).
* ``fetch_funding_rate_history``: ``/api/v1/contract/funding-rates`` (100 rows per call).
* ``fetch_market_leverage_tiers``: ``/api/v1/contracts/risk-limit/{symbol}``.

A 429 raises ``ExchangeRateLimitError`` and the feed pauses this venue.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, ClassVar

from nexus.adapters.cex.ccxt_base import to_decimal
from nexus.adapters.perp.ccxt_perp import CcxtPerpAdapter, _int_or_none
from nexus.adapters.perp.registry import perp_registry
from nexus.domain.errors import DataValidationError
from nexus.domain.perp import ZERO, MarkKline


@perp_registry.register("kucoin")
class KucoinFuturesAdapter(CcxtPerpAdapter):
    """KuCoin USDT-margined perpetual contracts."""

    name: ClassVar[str] = "kucoin"
    ccxt_id: ClassVar[str] = "kucoinfutures"
    order_book_limits: ClassVar[tuple[int, ...] | None] = (20, 100)
    kline_page_size: ClassVar[int] = 200

    def _market_mmr(self, info: Mapping[str, Any]) -> Decimal | None:
        return to_decimal(info.get("maintainMargin"))

    def _is_delisting(self, info: Mapping[str, Any]) -> bool:
        return info.get("expireDate") is not None

    async def _fetch_raw_tickers(self) -> Mapping[str, Any]:
        result: Mapping[str, Any] = await self._call(
            "fetch_bids_asks", lambda: self._rest.fetch_bids_asks()
        )
        return result

    async def _fetch_marks(self) -> Mapping[str, tuple[Decimal | None, Decimal | None]]:
        raw: Mapping[str, Any] = await self._call(
            "fetch_tickers", lambda: self._rest.fetch_tickers()
        )
        marks: dict[str, tuple[Decimal | None, Decimal | None]] = {}
        for symbol, entry in raw.items():
            if isinstance(entry, Mapping):
                mark = to_decimal(entry.get("markPrice"))
                index = to_decimal(entry.get("indexPrice"))
                marks[symbol] = (
                    mark if mark is not None and mark > ZERO else None,
                    index if index is not None and index > ZERO else None,
                )
        return marks

    def _parse_kline(self, row: Any) -> MarkKline | None:
        if not isinstance(row, list | tuple) or len(row) < 5:
            return None
        values = [to_decimal(v) for v in row[1:5]]
        ts = _int_or_none(row[0])
        if ts is None or any(v is None or v <= ZERO for v in values):
            return None
        prices = [v for v in values if v is not None]
        try:
            return MarkKline(
                open_ms=ts,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[2],
            )
        except DataValidationError:
            return None
