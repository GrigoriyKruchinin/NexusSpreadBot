"""HT1 PerpFeed: public perp market data for the hedged-transfer paper test (spec 4, 5.1).

One polling task per hedge venue, completely separate from the spot sweep (its own client, its own
health/backoff instance, no spot ``ExchangeDown`` events: log + counters only). It keeps an
in-memory cache that the (synchronous) HT code reads without any I/O:

* tickers and funding/mark per venue with their ages and stale flags;
* perp markets (30 min), incremental 1 m mark-kline cache per ``(venue, symbol)`` (24 h) and
  leverage tiers (1 h), filled by :meth:`request_prefetch` / the open-position watch (C5, C7);
* the relative-basis samples ``x = (bid_B - bid_H) / mid_H`` every ticker refresh (spec 5.1).

Contract: the loop never raises (errors are logged and counted), a rate-limit answer pauses only
that perp venue for ``rate_limit_backoff_s`` (no retry storm), and cancellation / ``stop`` ends
every task promptly. Read-only: only the :class:`IPerpMarketData` port is used, no credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypeVar

import structlog

from nexus.domain.clock import Clock
from nexus.domain.errors import ExchangeRateLimitError
from nexus.domain.models import ZERO
from nexus.domain.perp import FundingInfo, LeverageTier, MarkKline, PerpMarket, PerpTicker
from nexus.interfaces.perp import IPerpMarketData
from nexus.log import scrub
from nexus.scanner.health import ExchangeHealthTracker
from nexus.simulation.basis import BasisStore

log = structlog.get_logger(__name__)
T = TypeVar("T")

MINUTE_MS = 60_000
HOUR_MS = 3_600_000


@dataclass(frozen=True, slots=True)
class PerpFeedConfig:
    """Cadences and limits (defaults = spec section 13 / design review section 3)."""

    ticker_interval_s: float = 30.0
    funding_refresh_s: float = 60.0
    markets_refresh_s: float = 1800.0
    kline_window_h: int = 24
    kline_refresh_s: float = 900.0
    liq_check_s: float = 300.0
    tier_refresh_s: float = 3600.0
    call_timeout_s: float = 20.0
    rate_limit_backoff_s: float = 60.0
    down_after_failures: int = 3
    max_ticker_age_ms: int = 60_000
    max_funding_age_ms: int = 15 * MINUTE_MS
    basis_spot_max_age_ms: int = 15_000
    prefetch_per_cycle: int = 2
    per_symbol_funding_venues: frozenset[str] = frozenset({"okx"})
    """Venues whose funding is fetched per instrument (watched symbols only), not in bulk."""
    spot_venues: tuple[str, ...] = ()
    """Spot venues B of the basis keys."""


@dataclass(slots=True)
class _Kline:
    candles: dict[int, MarkKline] = field(default_factory=dict)
    loaded_ms: int | None = None
    """Last successful refresh (wall clock)."""


@dataclass(slots=True)
class _Venue:
    port: IPerpMarketData
    markets: dict[str, PerpMarket] = field(default_factory=dict)
    by_base: dict[str, str] = field(default_factory=dict)
    markets_at_ms: int | None = None
    tickers: Mapping[str, PerpTicker] = field(default_factory=dict)
    tickers_at_ms: int | None = None
    funding: dict[str, FundingInfo] = field(default_factory=dict)
    funding_at_ms: int | None = None
    klines: dict[str, _Kline] = field(default_factory=dict)
    tiers: dict[str, tuple[int, Sequence[LeverageTier] | None]] = field(default_factory=dict)
    watch: frozenset[str] = frozenset()
    open_symbols: frozenset[str] = frozenset()
    prefetch: dict[str, None] = field(default_factory=dict)
    """Ordered set of symbols waiting for klines + tiers."""
    last_liq_check_ms: int | None = None


class PerpFeed:
    """Cache + polling loops for the hedge venues' public perp data."""

    def __init__(
        self,
        ports: Mapping[str, IPerpMarketData],
        clock: Clock,
        config: PerpFeedConfig | None = None,
        basis: BasisStore | None = None,
    ) -> None:
        self._cfg = config or PerpFeedConfig()
        self._clock = clock
        self._venues = {name: _Venue(port) for name, port in ports.items()}
        self._health = ExchangeHealthTracker(
            down_after_failures=self._cfg.down_after_failures,
            rate_limit_backoff_ms=int(self._cfg.rate_limit_backoff_s * 1000),
        )
        self._basis = basis if basis is not None else BasisStore()
        self._spot: dict[tuple[str, str], tuple[Decimal, int]] = {}
        self._kline_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.counters: dict[str, int] = {}
        """Metrics without a metrics backend: errors, rate limits, basis samples and drops."""

    # ------------------------------------------------------------------ read API (sync)

    @property
    def venues(self) -> tuple[str, ...]:
        """Hedge venues served by this feed."""
        return tuple(self._venues)

    @property
    def basis(self) -> BasisStore:
        """The basis sample store fed by this feed."""
        return self._basis

    def market(self, venue: str, coin: str) -> PerpMarket | None:
        """Active linear USDT perp market of ``coin`` on ``venue``."""
        v = self._venues.get(venue)
        symbol = v.by_base.get(coin) if v else None
        return v.markets.get(symbol) if v and symbol else None

    def ticker(self, venue: str, symbol: str) -> PerpTicker | None:
        """Latest cached ticker (may be stale: check :meth:`is_stale`)."""
        v = self._venues.get(venue)
        return v.tickers.get(symbol) if v else None

    def funding(self, venue: str, symbol: str) -> FundingInfo | None:
        """Latest cached funding/mark (may be stale: check :meth:`funding_age_ms`)."""
        v = self._venues.get(venue)
        return v.funding.get(symbol) if v else None

    def ticker_age_ms(self, venue: str, now_ms: int | None = None) -> int | None:
        """Age of the venue's last successful ticker refresh; ``None`` = never loaded."""
        v = self._venues.get(venue)
        if v is None or v.tickers_at_ms is None:
            return None
        return max(0, (now_ms if now_ms is not None else self._clock.now_ms()) - v.tickers_at_ms)

    def funding_age_ms(self, venue: str, symbol: str, now_ms: int | None = None) -> int | None:
        """Age of the cached funding record of ``symbol``; ``None`` when absent."""
        info = self.funding(venue, symbol)
        if info is None:
            return None
        return max(
            0, (now_ms if now_ms is not None else self._clock.now_ms()) - info.received_at_ms
        )

    def is_stale(self, venue: str, now_ms: int | None = None) -> bool:
        """True when the venue's tickers are missing/too old, or it is paused or down."""
        now = now_ms if now_ms is not None else self._clock.now_ms()
        age = self.ticker_age_ms(venue, now)
        if age is None or age > self._cfg.max_ticker_age_ms:
            return True
        return self._health.is_paused(venue, now) or self._health.is_down(venue)

    def is_paused(self, venue: str, now_ms: int | None = None) -> bool:
        """True while the venue is in rate-limit backoff."""
        return self._health.is_paused(venue, now_ms if now_ms is not None else self._clock.now_ms())

    def klines(self, venue: str, symbol: str) -> list[MarkKline]:
        """Cached 1 m mark candles of ``symbol``, ascending."""
        v = self._venues.get(venue)
        entry = v.klines.get(symbol) if v else None
        return [entry.candles[k] for k in sorted(entry.candles)] if entry else []

    def kline_coverage(self, venue: str, symbol: str, now_ms: int | None = None) -> Decimal:
        """Share of the last ``kline_window_h`` hours (closed minutes) that have a candle."""
        now = now_ms if now_ms is not None else self._clock.now_ms()
        entry = self._venues[venue].klines.get(symbol) if venue in self._venues else None
        if entry is None:
            return ZERO
        end = now // MINUTE_MS * MINUTE_MS  # exclusive: the running minute is not closed
        start = end - self._cfg.kline_window_h * HOUR_MS
        expected = (end - start) // MINUTE_MS
        have = sum(1 for t in entry.candles if start <= t < end)
        return Decimal(have) / Decimal(expected)

    def tiers(self, venue: str, symbol: str) -> tuple[int, Sequence[LeverageTier] | None] | None:
        """``(loaded_at_ms, tiers-or-None)`` once a tier fetch happened, else ``None``."""
        v = self._venues.get(venue)
        return v.tiers.get(symbol) if v else None

    def tiers_ready(self, venue: str, symbol: str, now_ms: int | None = None) -> bool:
        """Tiers loaded (and fresh) and public; ``None``/missing tiers are not ready."""
        entry = self.tiers(venue, symbol)
        now = now_ms if now_ms is not None else self._clock.now_ms()
        if entry is None or entry[1] is None:
            return False
        return now - entry[0] <= int(self._cfg.tier_refresh_s * 1000) * 2

    # ------------------------------------------------------------------ write API (sync)

    def set_watch(self, venue: str, symbols: Iterable[str]) -> None:
        """Symbols whose funding is polled on per-instrument venues (candidates + open)."""
        if venue in self._venues:
            self._venues[venue].watch = frozenset(symbols)

    def set_open(self, venue: str, symbols: Iterable[str]) -> None:
        """Symbols with an open position: their klines are refreshed every ``liq_check_s``."""
        if venue in self._venues:
            self._venues[venue].open_symbols = frozenset(symbols)

    def request_prefetch(self, venue: str, symbol: str) -> None:
        """Queue klines + tiers for ``symbol`` (served by the venue loop, never inline)."""
        if venue in self._venues:
            self._venues[venue].prefetch.setdefault(symbol, None)

    def update_spot(self, venue: str, bids: Mapping[str, tuple[Decimal, int]]) -> None:
        """Latest spot bids ``{coin: (bid, received_at_ms)}`` of spot venue B (sync, in-memory)."""
        for coin, value in bids.items():
            self._spot[venue, coin] = value

    # ------------------------------------------------------------------ polling

    async def run(self, stop: asyncio.Event) -> None:
        """Poll every hedge venue concurrently until ``stop`` is set. Never raises."""
        tasks = [asyncio.create_task(self._venue_loop(name, stop)) for name in self._venues]
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _venue_loop(self, venue: str, stop: asyncio.Event) -> None:
        while not stop.is_set():
            started = self._clock.now_ms()
            try:
                if not await self._unless_stopped(self.poll_venue(venue), stop):
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop must survive anything
                self._count("loop_errors")
                log.error("perp_feed_loop_error", venue=venue, error=scrub(repr(exc))[:200])
            elapsed = (self._clock.now_ms() - started) / 1000
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=max(0.0, self._cfg.ticker_interval_s - elapsed)
                )

    @staticmethod
    async def _unless_stopped(work: Awaitable[object], stop: asyncio.Event) -> bool:
        """Run ``work`` until done or ``stop``; False when stopped (work cancelled)."""
        task = asyncio.ensure_future(work)
        stopper = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if task.cancelled():
            return False
        if (error := task.exception()) is not None:
            raise error
        return not stop.is_set()

    async def poll_venue(self, venue: str) -> None:
        """One polling cycle of one venue (public so tests and S13 can drive it)."""
        v = self._venues[venue]
        now = self._clock.now_ms()
        if self._health.is_paused(venue, now):
            self._count("paused_cycles")
            return
        if v.markets_at_ms is None or now - v.markets_at_ms >= self._cfg.markets_refresh_s * 1000:
            await self._refresh_markets(venue, v)
        if not await self._refresh_tickers(venue, v):
            return
        self._sample_basis(venue, v)
        now = self._clock.now_ms()
        if v.funding_at_ms is None or now - v.funding_at_ms >= self._cfg.funding_refresh_s * 1000:
            await self._refresh_funding(venue, v)
        await self._refresh_history(venue, v)

    async def _call(self, venue: str, what: str, coro: Awaitable[T]) -> T | None:
        """Bounded port call; failures are recorded and swallowed (``None``)."""
        try:
            return await asyncio.wait_for(coro, timeout=self._cfg.call_timeout_s)
        except asyncio.CancelledError:
            raise
        except ExchangeRateLimitError as exc:
            self._count("rate_limited")
            self._health.record_failure(venue, self._clock.now_ms(), str(exc), rate_limited=True)
            log.warning("perp_feed_rate_limited", venue=venue, call=what)
        except Exception as exc:
            self._count("errors")
            message = scrub(repr(exc))[:200]
            event = self._health.record_failure(venue, self._clock.now_ms(), message)
            log.warning("perp_feed_call_failed", venue=venue, call=what, error=message)
            if event is not None:
                log.error("perp_feed_venue_down", venue=venue)
        return None

    async def _refresh_markets(self, venue: str, v: _Venue) -> None:
        markets = await self._call(venue, "markets", v.port.load_perp_markets())
        if markets is None:
            return
        v.markets = {m.symbol: m for m in markets}
        v.by_base = {m.base: m.symbol for m in markets if m.active and not m.delisting}
        v.markets_at_ms = self._clock.now_ms()

    async def _refresh_tickers(self, venue: str, v: _Venue) -> bool:
        tickers = await self._call(venue, "tickers", v.port.fetch_perp_tickers())
        if tickers is None:
            return False
        v.tickers = tickers
        v.tickers_at_ms = self._clock.now_ms()
        recovered = self._health.record_success(venue, v.tickers_at_ms)
        if recovered is not None:
            log.info("perp_feed_venue_recovered", venue=venue)
        return True

    async def _refresh_funding(self, venue: str, v: _Venue) -> None:
        symbols: list[str] | None = None
        if venue in self._cfg.per_symbol_funding_venues:
            symbols = sorted(v.watch)
            if not symbols:
                v.funding_at_ms = self._clock.now_ms()
                return
        funding = await self._call(venue, "funding", v.port.fetch_funding(symbols))
        if funding is None:
            return
        v.funding.update(funding)
        v.funding_at_ms = self._clock.now_ms()

    async def _refresh_history(self, venue: str, v: _Venue) -> None:
        """Klines/tiers for queued prefetches and klines of open positions (C5, C7)."""
        now = self._clock.now_ms()
        for symbol in list(v.prefetch)[: self._cfg.prefetch_per_cycle]:
            ok_k = await self.refresh_klines(venue, symbol, force=True)
            ok_t = await self.refresh_tiers(venue, symbol)
            if ok_k and ok_t:
                v.prefetch.pop(symbol, None)
        if v.open_symbols and (
            v.last_liq_check_ms is None or now - v.last_liq_check_ms >= self._cfg.liq_check_s * 1000
        ):
            v.last_liq_check_ms = now
            for symbol in sorted(v.open_symbols):
                await self.refresh_klines(venue, symbol, force=True)

    async def refresh_klines(self, venue: str, symbol: str, *, force: bool = False) -> bool:
        """Incremental 24 h cache refresh; False when the fetch failed or the venue is paused."""
        v = self._venues[venue]
        key = (venue, symbol)
        lock = self._kline_locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock.now_ms()
            if self._health.is_paused(venue, now):
                return False
            entry = v.klines.setdefault(symbol, _Kline())
            if (
                not force
                and entry.loaded_ms is not None
                and now - entry.loaded_ms < self._cfg.kline_refresh_s * 1000
            ):
                return True
            window_start = now - self._cfg.kline_window_h * HOUR_MS
            # Re-fetch the newest cached candle: it may have been the still-running minute.
            since = max(window_start, max(entry.candles, default=window_start))
            fetched = await self._call(
                venue, "klines", v.port.fetch_mark_klines(symbol, since, now)
            )
            if fetched is None:
                return False
            for candle in fetched:
                entry.candles[candle.open_ms] = candle
            for stale in [t for t in entry.candles if t < window_start]:
                del entry.candles[stale]
            entry.loaded_ms = self._clock.now_ms()
            return True

    async def refresh_tiers(self, venue: str, symbol: str) -> bool:
        """Load the public MMR tiers (cached ``tier_refresh_s``); False on failure."""
        v = self._venues[venue]
        now = self._clock.now_ms()
        cached = v.tiers.get(symbol)
        if cached is not None and now - cached[0] < self._cfg.tier_refresh_s * 1000:
            return True
        if self._health.is_paused(venue, now):
            return False
        try:
            tiers = await asyncio.wait_for(
                v.port.fetch_leverage_tiers(symbol), timeout=self._cfg.call_timeout_s
            )
        except asyncio.CancelledError:
            raise
        except ExchangeRateLimitError as exc:
            self._count("rate_limited")
            self._health.record_failure(venue, now, str(exc), rate_limited=True)
            return False
        except Exception as exc:
            self._count("errors")
            log.warning(
                "perp_feed_call_failed", venue=venue, call="tiers", error=scrub(repr(exc))[:200]
            )
            return False
        v.tiers[symbol] = (self._clock.now_ms(), tiers)
        return True

    # ------------------------------------------------------------------ basis

    def _sample_basis(self, venue: str, v: _Venue) -> None:
        """One sample per ``(coin, B, H)``; bad inputs are dropped, never imputed."""
        for (spot_venue, coin), (bid_b, spot_ts) in self._spot.items():
            if spot_venue not in self._cfg.spot_venues:
                continue
            symbol = v.by_base.get(coin)
            ticker = v.tickers.get(symbol) if symbol else None
            if ticker is None:
                continue
            if (
                ticker.bid is None
                or ticker.ask is None
                or ticker.bid <= ZERO
                or ticker.bid > ticker.ask
                or bid_b <= ZERO
                or ticker.received_at_ms - spot_ts > self._cfg.basis_spot_max_age_ms
            ):
                self._count("basis_dropped")
                continue
            mid = (ticker.bid + ticker.ask) / 2
            x = (bid_b - ticker.bid) / mid
            if self._basis.add((coin, spot_venue, venue), ticker.received_at_ms, x):
                self._count("basis_samples")

    def _count(self, name: str, n: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + n


def hedge_venues_of(sets: Mapping[str, Collection[str]]) -> tuple[str, ...]:
    """Distinct hedge venues of all enabled HT sets (the venues that need a perp client)."""
    return tuple(sorted({v for hedge in sets.values() for v in hedge}))
