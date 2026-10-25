"""Binance USD-M futures (linear USDT) market data (public, no credentials).

Host ``fapi.binance.com`` (ccxt ``binanceusdm``). Limits are the working numbers from the Binance
docs (IP weight budget 2400 / min, own host) and are not re-measured here:

* ``load_markets``: ``/fapi/v1/exchangeInfo`` (weight 1). ``fetchCurrencies`` is disabled, otherwise
  ccxt would call the signed ``sapi`` currency endpoint.
* ``fetch_bids_asks``: ``/fapi/v1/ticker/bookTicker`` (bulk, weight 5).
* ``fetch_order_book``: ``/fapi/v1/depth`` (limits 5/10/20/50/100/500/1000, weight 2 to 20); amounts
  are already in base units (contract size 1).
* ``fetch_funding_rates``: ``/fapi/v1/premiumIndex`` (bulk, weight 10; mark, index, rate, next time)
  plus ``fetch_funding_intervals``: ``/fapi/v1/fundingInfo`` (symbols with a 4 h or 1 h interval).
* ``fetch_mark_ohlcv``: ``/fapi/v1/markPriceKlines`` (up to 1500 rows per call: 24 h in one call).
* ``fetch_funding_rate_history``: ``/fapi/v1/fundingRate`` (up to 1000 rows). Binance stamps a few
  milliseconds after the funding time; times are rounded to the second.
* Leverage brackets (``/fapi/v1/leverageBracket``) are SIGNED and never called:
  ``fetch_leverage_tiers`` returns ``None`` (HT assumes the configured leverage and default MMR).

A 429/418 raises ``ExchangeRateLimitError`` and the feed pauses this venue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from nexus.adapters.perp.ccxt_perp import CcxtPerpAdapter
from nexus.adapters.perp.registry import perp_registry
from nexus.domain.errors import ExchangeError
from nexus.domain.perp import FundingPayment, LeverageTier

_PERPETUAL_DELIVERY_MS = 4_000_000_000_000
"""Binance reports ``deliveryDate`` 4133404800000 (year 2100) for live perpetuals."""


@perp_registry.register("binance")
class BinanceUsdmAdapter(CcxtPerpAdapter):
    """Binance USDT-margined perpetual futures."""

    name: ClassVar[str] = "binance"
    ccxt_id: ClassVar[str] = "binanceusdm"
    ccxt_options: ClassVar[Mapping[str, Any]] = {
        "defaultType": "swap",
        "fetchCurrencies": False,
    }
    order_book_limits: ClassVar[tuple[int, ...] | None] = (5, 10, 20, 50, 100, 500, 1000)
    kline_page_size: ClassVar[int] = 1500
    funding_page_size: ClassVar[int] = 1000

    def _is_delisting(self, info: Mapping[str, Any]) -> bool:
        delivery = info.get("deliveryDate")
        try:
            return delivery is not None and int(delivery) < _PERPETUAL_DELIVERY_MS
        except (TypeError, ValueError):
            return False

    async def _fetch_raw_tickers(self) -> Mapping[str, Any]:
        result: Mapping[str, Any] = await self._call(
            "fetch_bids_asks", lambda: self._rest.fetch_bids_asks()
        )
        return result

    async def _fetch_funding_rates(self, symbols: Sequence[str] | None) -> Mapping[str, Any]:
        rates = await super()._fetch_funding_rates(symbols)
        try:
            intervals: Mapping[str, Any] = await self._call(
                "fetch_funding_intervals", lambda: self._rest.fetch_funding_intervals()
            )
        except ExchangeError as exc:
            self._log.info("funding_intervals_unavailable", error=str(exc))
            return rates
        merged: dict[str, Any] = {}
        for symbol, entry in rates.items():
            extra = intervals.get(symbol)
            interval = extra.get("interval") if isinstance(extra, Mapping) else None
            merged[symbol] = (
                {**entry, "interval": interval}
                if isinstance(entry, Mapping) and interval is not None
                else entry
            )
        return merged

    async def fetch_funding_history(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[FundingPayment]:
        payments = await super().fetch_funding_history(symbol, since_ms, until_ms)
        return tuple(
            FundingPayment(
                symbol=p.symbol,
                funding_time_ms=round(p.funding_time_ms / 1000) * 1000,
                rate=p.rate,
            )
            for p in payments
        )

    async def fetch_leverage_tiers(self, symbol: str) -> Sequence[LeverageTier] | None:
        """Not public on Binance (signed ``leverageBracket``): never requested."""
        return None
