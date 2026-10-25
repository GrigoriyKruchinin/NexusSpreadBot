"""Shared ccxt-based perpetual-swap market-data adapter (public, read-only, no credentials).

ADR 0001 / ADR 0009: the client is created **without** ``apiKey``/``secret``/``password`` (the
constructor has no credentials parameter), ``fetchCurrencies`` is disabled (otherwise ccxt calls
private currency endpoints) and the read-only guard blocks every non-GET request. Only public
endpoints are used: markets, tickers, order books, funding, mark-price klines, funding history and
(where public) maintenance-margin tiers. Nothing here sets leverage or margin, places orders or
moves funds.

ccxt returns floats; every value is converted into the Decimal domain types here. Order book amounts
are multiplied by ``contractSize`` so callers only see base units.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from functools import partial
from typing import Any, ClassVar, TypeVar

import ccxt
import ccxt.async_support as ccxt_async
import structlog

from nexus.adapters.cex.ccxt_base import install_read_only_guard, to_decimal
from nexus.adapters.registry import AdapterOptions
from nexus.domain.clock import Clock, SystemClock
from nexus.domain.errors import (
    ConfigurationError,
    DataValidationError,
    ExchangeDataError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    ReadOnlyViolationError,
)
from nexus.domain.models import OrderBook, PriceLevel
from nexus.domain.perp import (
    ZERO,
    FundingInfo,
    FundingPayment,
    LeverageTier,
    MarkKline,
    PerpMarket,
    PerpTicker,
)
from nexus.interfaces.perp import IPerpMarketData
from nexus.log import scrub

T = TypeVar("T")
log = structlog.get_logger(__name__)

_URL_RE = re.compile(r"https?://\S+|wss?://\S+")
_HOURS_RE = re.compile(r"^(\d+(?:\.\d+)?)h$")
_MS_PER_MINUTE = 60_000
_MS_PER_HOUR = 3_600_000
_MAX_PAGES = 40
"""Hard bound for paged history requests (24 h of 100-row pages is 15 calls)."""


class CcxtPerpAdapter(IPerpMarketData):
    """Read-only linear USDT perpetual market data backed by a credential-less ccxt client."""

    name: ClassVar[str]
    ccxt_id: ClassVar[str]
    ccxt_options: ClassVar[Mapping[str, Any]] = {"defaultType": "swap", "fetchCurrencies": False}
    order_book_limits: ClassVar[tuple[int, ...] | None] = None
    """Allowed ``limit`` values for order book requests (``None`` = any up to the max)."""
    max_order_book_limit: ClassVar[int] = 200
    kline_page_size: ClassVar[int] = 100
    funding_page_size: ClassVar[int] = 100
    max_attempts: ClassVar[int] = 3
    retry_backoff_s: ClassVar[float] = 0.5

    def __init__(
        self,
        options: AdapterOptions,
        *,
        clock: Clock | None = None,
        rest_client: Any = None,
    ) -> None:
        """Create the adapter. ``rest_client`` lets tests inject a ccxt-compatible double."""
        self._options = options
        self._clock: Clock = clock or SystemClock()
        self._rest: Any = rest_client or getattr(ccxt_async, self.ccxt_id)(self._client_config())
        if getattr(self._rest, "apiKey", None) or getattr(self._rest, "secret", None):
            msg = f"[{self.name}:perp] perp clients must be created without credentials"
            raise ReadOnlyViolationError(msg)
        if hasattr(self._rest, "fetch"):
            install_read_only_guard(self._rest, f"{self.name}:perp")
        if getattr(self._rest, "precisionMode", ccxt.TICK_SIZE) != ccxt.TICK_SIZE:
            msg = f"{self.name}: unsupported ccxt precision mode (expected TICK_SIZE)"
            raise ConfigurationError(msg)
        self._markets: dict[str, PerpMarket] = {}
        self._closed = False
        self._log = log.bind(exchange=self.name, kind="perp")

    # ------------------------------------------------------------------ lifecycle

    def _client_config(self) -> dict[str, Any]:
        """ccxt client config. Deliberately has no credential keys."""
        return {
            "enableRateLimit": True,
            "timeout": self._options.timeout_ms,
            "options": dict(self.ccxt_options),
        }

    async def close(self) -> None:
        """Close the REST client."""
        self._closed = True
        try:
            await self._rest.close()
        except Exception as exc:
            self._log.warning("adapter_close_failed", error=scrub(repr(exc)))

    # ------------------------------------------------------------------ calls

    async def _call(self, operation: str, func: Callable[[], Awaitable[T]]) -> T:
        """Run a ccxt call with error translation, an overall timeout and bounded retries."""
        timeout_s = self._options.timeout_ms / 1000 * 2
        attempt = 1
        while True:
            cause: BaseException
            try:
                return await asyncio.wait_for(func(), timeout=timeout_s)
            except TimeoutError as exc:
                cause = exc
                error: ExchangeError = ExchangeUnavailableError(
                    self.name, f"{operation}: timed out"
                )
            except ccxt.BaseError as exc:
                cause = exc
                error = self._translate(operation, exc)
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                cause = exc
                error = ExchangeDataError(self.name, f"{operation}: malformed data ({exc!r:.120})")
            if not isinstance(error, ExchangeUnavailableError) or attempt >= self.max_attempts:
                error.add_note(f"cause: {type(cause).__name__}")
                raise error from None
            self._log.info("retrying", operation=operation, attempt=attempt, error=str(error))
            await asyncio.sleep(self.retry_backoff_s * 2 ** (attempt - 1))
            attempt += 1

    def _translate(self, operation: str, exc: Exception) -> ExchangeError:
        message = scrub(_URL_RE.sub("<url>", str(exc)))[:160]
        detail = f"{operation}: {type(exc).__name__}: {message}"
        if isinstance(exc, ccxt.RateLimitExceeded | ccxt.DDoSProtection):
            return ExchangeRateLimitError(self.name, detail)
        if isinstance(exc, ccxt.NetworkError):
            return ExchangeUnavailableError(self.name, detail)
        return ExchangeDataError(self.name, detail)

    # ------------------------------------------------------------------ markets

    async def load_perp_markets(self) -> Sequence[PerpMarket]:
        """Linear USDT perpetuals with lot data; inactive/delisting ones are flagged."""
        raw: Mapping[str, Any] = await self._call(
            "load_markets", lambda: self._rest.load_markets(True)
        )
        markets: dict[str, PerpMarket] = {}
        for symbol, market in raw.items():
            if not self._is_linear_usdt_perp(market):
                continue
            try:
                markets[symbol] = self._parse_market(symbol, market)
            except (DataValidationError, KeyError, TypeError) as exc:
                self._log.warning("perp_market_skipped", symbol=symbol, error=str(exc))
        self._markets = markets
        return tuple(markets.values())

    @staticmethod
    def _is_linear_usdt_perp(market: Any) -> bool:
        return (
            isinstance(market, Mapping)
            and bool(market.get("swap"))
            and bool(market.get("linear"))
            and market.get("quote") == "USDT"
            and market.get("settle") == "USDT"
            and market.get("base") is not None
        )

    def _parse_market(self, symbol: str, market: Mapping[str, Any]) -> PerpMarket:
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        step = to_decimal(precision.get("amount"))
        if step is None:
            msg = f"{self.name}:{symbol}: no amount step"
            raise DataValidationError(msg)
        min_qty = to_decimal((limits.get("amount") or {}).get("min"))
        contract_size = to_decimal(market.get("contractSize"))
        if contract_size is None:
            msg = f"{self.name}:{symbol}: no contract size"
            raise DataValidationError(msg)
        info = market.get("info")
        info = info if isinstance(info, Mapping) else {}
        return PerpMarket(
            exchange=self.name,
            symbol=symbol,
            base=str(market["base"]),
            contract_size=contract_size,
            amount_step=step,
            min_qty=min_qty if min_qty is not None else step,
            max_leverage=to_decimal((limits.get("leverage") or {}).get("max")),
            mmr=self._market_mmr(info),
            taker_fee=to_decimal(market.get("taker")),
            active=market.get("active") is not False,
            delisting=self._is_delisting(info),
        )

    def _market_mmr(self, info: Mapping[str, Any]) -> Decimal | None:
        """Base maintenance margin rate from the raw market info, when published there."""
        return None

    def _is_delisting(self, info: Mapping[str, Any]) -> bool:
        """True when the raw market info announces an expiry/delivery of the perpetual."""
        return False

    async def _ensure_markets(self) -> dict[str, PerpMarket]:
        if not self._markets:
            await self.load_perp_markets()
        return self._markets

    # ------------------------------------------------------------------ tickers

    async def fetch_perp_tickers(self) -> Mapping[str, PerpTicker]:
        """Best bid/ask of every known perp (one bulk request)."""
        markets = await self._ensure_markets()
        started = self._clock.now_ms()
        raw = await self._fetch_raw_tickers()
        tickers: dict[str, PerpTicker] = {}
        for symbol, entry in raw.items():
            if symbol not in markets or not isinstance(entry, Mapping):
                continue
            bid = _positive(entry.get("bid"))
            ask = _positive(entry.get("ask"))
            try:
                tickers[symbol] = PerpTicker(
                    exchange=self.name,
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    mark=_positive(entry.get("markPrice")),
                    received_at_ms=started,
                )
            except DataValidationError as exc:
                self._log.info("perp_ticker_skipped", symbol=symbol, error=str(exc))
        return tickers

    async def _fetch_raw_tickers(self) -> Mapping[str, Any]:
        """Bulk bid/ask source (unified ccxt tickers). Overridden where tickers lack bid/ask."""
        result: Mapping[str, Any] = await self._call(
            "fetch_tickers", lambda: self._rest.fetch_tickers()
        )
        return result

    # ------------------------------------------------------------------ order book

    def order_book_limit(self, depth: int) -> int:
        """Translate a desired depth into a limit the venue accepts."""
        allowed = self.order_book_limits
        if allowed is None:
            return max(1, min(depth, self.max_order_book_limit))
        candidates = [limit for limit in allowed if limit >= depth]
        return min(candidates) if candidates else max(allowed)

    async def fetch_perp_order_book(self, symbol: str, depth: int) -> OrderBook:
        """REST order book with amounts converted from contracts to base units."""
        markets = await self._ensure_markets()
        market = markets.get(symbol)
        if market is None:
            msg = f"{self.name}: unknown perp {symbol}"
            raise ExchangeDataError(self.name, msg)
        limit = self.order_book_limit(depth)
        started = self._clock.now_ms()
        raw: Any = await self._call(
            f"fetch_order_book {symbol}", lambda: self._rest.fetch_order_book(symbol, limit)
        )
        if not isinstance(raw, Mapping):
            msg = f"fetch_order_book {symbol}: malformed payload"
            raise ExchangeDataError(self.name, msg)
        timestamp = raw.get("timestamp")
        try:
            return OrderBook(
                exchange=self.name,
                symbol=symbol,
                bids=_levels(raw.get("bids"), depth, market.contract_size),
                asks=_levels(raw.get("asks"), depth, market.contract_size),
                timestamp_ms=int(timestamp) if isinstance(timestamp, int | float) else started,
                received_at_ms=started,
            )
        except DataValidationError as exc:
            raise ExchangeDataError(self.name, str(exc)) from exc

    # ------------------------------------------------------------------ funding

    async def fetch_funding(
        self, symbols: Sequence[str] | None = None
    ) -> Mapping[str, FundingInfo]:
        """Current funding rate, next funding time, mark and index price."""
        markets = await self._ensure_markets()
        wanted = None if symbols is None else [s for s in symbols if s in markets]
        started = self._clock.now_ms()
        raw = await self._fetch_funding_rates(wanted)
        marks: Mapping[str, tuple[Decimal | None, Decimal | None]] | None = None
        result: dict[str, FundingInfo] = {}
        for symbol, entry in raw.items():
            if symbol not in markets or not isinstance(entry, Mapping):
                continue
            rate = to_decimal(entry.get("fundingRate"))
            if rate is None:
                continue
            mark = _positive(entry.get("markPrice"))
            index = _positive(entry.get("indexPrice"))
            if mark is None and marks is None:
                marks = await self._fetch_marks()
            if mark is None and marks is not None:
                mark, fallback_index = marks.get(symbol, (None, None))
                index = index or fallback_index
            try:
                result[symbol] = FundingInfo(
                    exchange=self.name,
                    symbol=symbol,
                    rate=rate,
                    next_funding_ms=_int_or_none(entry.get("fundingTimestamp")),
                    interval_h=_interval_hours(entry),
                    mark_price=mark,
                    index_price=index,
                    received_at_ms=started,
                )
            except DataValidationError as exc:
                self._log.info("funding_skipped", symbol=symbol, error=str(exc))
        return result

    async def _fetch_funding_rates(self, symbols: Sequence[str] | None) -> Mapping[str, Any]:
        """Unified ccxt funding entries by symbol (bulk where the venue allows)."""
        result: Mapping[str, Any] = await self._call(
            "fetch_funding_rates", lambda: self._rest.fetch_funding_rates(symbols)
        )
        return result

    async def _fetch_marks(self) -> Mapping[str, tuple[Decimal | None, Decimal | None]]:
        """Bulk ``(mark, index)`` prices by symbol, for venues whose funding entry lacks them."""
        raw: Mapping[str, Any] = await self._call(
            "fetch_mark_prices", lambda: self._rest.fetch_mark_prices()
        )
        return {
            symbol: (_positive(entry.get("markPrice")), _positive(entry.get("indexPrice")))
            for symbol, entry in raw.items()
            if isinstance(entry, Mapping)
        }

    # ------------------------------------------------------------------ history

    async def fetch_mark_klines(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[MarkKline]:
        """1 m mark-price candles in ``[since_ms, until_ms)``, ascending, paged."""
        await self._ensure_markets()
        candles: dict[int, MarkKline] = {}
        cursor = since_ms
        for _ in range(_MAX_PAGES):
            page_start = cursor
            rows: Sequence[Any] = await self._call(
                f"fetch_mark_ohlcv {symbol}",
                partial(
                    self._rest.fetch_mark_ohlcv, symbol, "1m", page_start, self.kline_page_size
                ),
            )
            newest = cursor
            reached_end = False
            for row in rows:
                kline = self._parse_kline(row)
                if kline is None:
                    continue
                reached_end = reached_end or kline.open_ms >= until_ms
                if since_ms <= kline.open_ms < until_ms:
                    candles[kline.open_ms] = kline
                    newest = max(newest, kline.open_ms + _MS_PER_MINUTE)
            if reached_end or newest <= cursor or newest >= until_ms:
                break
            cursor = newest
        return tuple(candles[key] for key in sorted(candles))

    def _parse_kline(self, row: Any) -> MarkKline | None:
        """ccxt row ``[ts, open, high, low, close, ...]`` -> candle (``None`` when unusable)."""
        if not isinstance(row, list | tuple) or len(row) < 5:
            return None
        values = [to_decimal(v) for v in row[1:5]]
        ts = _int_or_none(row[0])
        if ts is None or any(v is None or v <= ZERO for v in values):
            return None
        o, h, low, c = (v for v in values if v is not None)
        try:
            return MarkKline(open_ms=ts, open=o, high=h, low=low, close=c)
        except DataValidationError:
            self._log.info("mark_kline_skipped", ts=ts)
            return None

    async def fetch_funding_history(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[FundingPayment]:
        """Settled funding rates in ``[since_ms, until_ms)``, ascending."""
        await self._ensure_markets()
        payments: dict[int, FundingPayment] = {}
        cursor = since_ms
        for _ in range(_MAX_PAGES):
            page_start = cursor
            rows: Sequence[Any] = await self._call(
                f"fetch_funding_rate_history {symbol}",
                partial(
                    self._rest.fetch_funding_rate_history,
                    symbol,
                    page_start,
                    self.funding_page_size,
                ),
            )
            newest = cursor
            reached_end = False
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                rate = to_decimal(row.get("fundingRate"))
                ts = _int_or_none(row.get("timestamp"))
                if rate is None or ts is None:
                    continue
                reached_end = reached_end or ts >= until_ms
                if not since_ms <= ts < until_ms:
                    continue
                try:
                    payments[ts] = FundingPayment(symbol=symbol, funding_time_ms=ts, rate=rate)
                except DataValidationError:
                    self._log.info("funding_history_skipped", ts=ts)
                    continue
                newest = max(newest, ts + 1)
            if reached_end or newest <= cursor or newest >= until_ms:
                break
            cursor = newest
        return tuple(payments[key] for key in sorted(payments))

    async def fetch_leverage_tiers(self, symbol: str) -> Sequence[LeverageTier] | None:
        """Public maintenance-margin tiers; ``None`` when the venue serves them only signed."""
        await self._ensure_markets()
        rows: Sequence[Any] = await self._call(
            f"fetch_market_leverage_tiers {symbol}",
            lambda: self._rest.fetch_market_leverage_tiers(symbol),
        )
        tiers: list[LeverageTier] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            low = to_decimal(row.get("minNotional"))
            high = to_decimal(row.get("maxNotional"))
            leverage = to_decimal(row.get("maxLeverage"))
            mmr = to_decimal(row.get("maintenanceMarginRate"))
            if low is None or leverage is None or mmr is None:
                continue
            try:
                tiers.append(
                    LeverageTier(
                        min_notional=low, max_notional=high, max_leverage=leverage, mmr=mmr
                    )
                )
            except DataValidationError:
                self._log.info("leverage_tier_skipped", symbol=symbol)
        return tuple(sorted(tiers, key=lambda tier: tier.min_notional))


def _positive(value: Any) -> Decimal | None:
    number = to_decimal(value)
    return number if number is not None and number > ZERO else None


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _interval_hours(entry: Mapping[str, Any]) -> Decimal | None:
    """Funding interval in hours from the unified ``interval`` string or the two funding times."""
    text = entry.get("interval")
    if isinstance(text, str):
        match = _HOURS_RE.match(text)
        if match:
            return Decimal(match.group(1))
    current = _int_or_none(entry.get("fundingTimestamp"))
    upcoming = _int_or_none(entry.get("nextFundingTimestamp"))
    if current is not None and upcoming is not None and upcoming > current:
        return Decimal(upcoming - current) / _MS_PER_HOUR
    return None


def _levels(raw_levels: Any, depth: int, contract_size: Decimal) -> tuple[PriceLevel, ...]:
    levels: list[PriceLevel] = []
    for entry in raw_levels or ():
        if len(levels) >= depth:
            break
        if not isinstance(entry, list | tuple) or len(entry) < 2:
            continue
        price = to_decimal(entry[0])
        amount = to_decimal(entry[1])
        if price is None or amount is None or price <= ZERO or amount <= ZERO:
            continue
        levels.append(PriceLevel(price, amount * contract_size))
    return tuple(levels)
