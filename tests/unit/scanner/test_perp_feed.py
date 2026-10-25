"""HT1 S12: PerpFeed cadence, per-venue pause, stale flags, caches, basis, stop and never-raise."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal as D
from typing import ClassVar

import pytest

from nexus.domain.errors import ExchangeRateLimitError
from nexus.domain.models import OrderBook
from nexus.domain.perp import (
    FundingInfo,
    FundingPayment,
    LeverageTier,
    MarkKline,
    PerpMarket,
    PerpTicker,
)
from nexus.interfaces.perp import IPerpMarketData
from nexus.scanner.perp_feed import MINUTE_MS, PerpFeed, PerpFeedConfig, hedge_venues_of

T0 = 1_700_000_040_000  # multiple of 60 000


@dataclass
class Clock:
    now: int = T0

    def now_ms(self) -> int:
        return self.now


class FakePort(IPerpMarketData):
    name: ClassVar[str] = "fake"

    def __init__(self, venue: str = "okx") -> None:
        self.venue = venue
        self.calls: dict[str, int] = {}
        self.fail: Exception | None = None
        self.tier_result: Sequence[LeverageTier] | None = [
            LeverageTier(D(0), None, D(10), D("0.01"))
        ]
        self.klines: list[MarkKline] = []
        self.kline_since: list[int] = []
        self.funding_symbols: list[Sequence[str] | None] = []
        self.hang = False
        self.bid = D("100")
        self.clock: Clock | None = None

    def _hit(self, what: str) -> None:
        self.calls[what] = self.calls.get(what, 0) + 1
        if self.fail is not None:
            raise self.fail

    async def load_perp_markets(self) -> Sequence[PerpMarket]:
        self._hit("markets")
        return [PerpMarket(self.venue, "ABC/USDT:USDT", "ABC", D(1), D("0.1"), D(0))]

    async def fetch_perp_tickers(self) -> Mapping[str, PerpTicker]:
        if self.hang:
            await asyncio.sleep(3600)
        self._hit("tickers")
        now = self.clock.now if self.clock else T0
        t = PerpTicker(self.venue, "ABC/USDT:USDT", self.bid, self.bid + 1, D("100"), now)
        return {t.symbol: t}

    async def fetch_perp_order_book(self, symbol: str, depth: int) -> OrderBook:
        raise NotImplementedError

    async def fetch_funding(
        self, symbols: Sequence[str] | None = None
    ) -> Mapping[str, FundingInfo]:
        self._hit("funding")
        self.funding_symbols.append(symbols)
        now = self.clock.now if self.clock else T0
        f = FundingInfo(
            self.venue, "ABC/USDT:USDT", D("0.0001"), now + 3_600_000, D(8), D(100), D(100), now
        )
        return {f.symbol: f}

    async def fetch_mark_klines(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[MarkKline]:
        self._hit("klines")
        self.kline_since.append(since_ms)
        return [k for k in self.klines if since_ms <= k.open_ms < until_ms]

    async def fetch_funding_history(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[FundingPayment]:
        raise NotImplementedError

    async def fetch_leverage_tiers(self, symbol: str) -> Sequence[LeverageTier] | None:
        self._hit("tiers")
        return self.tier_result

    async def close(self) -> None:
        return None


def feed(*ports: FakePort, clock: Clock | None = None, **cfg: object) -> tuple[PerpFeed, Clock]:
    clock = clock or Clock()
    for p in ports:
        p.clock = clock
    config = PerpFeedConfig(spot_venues=("binance",), **cfg)  # type: ignore[arg-type]
    return PerpFeed({p.venue: p for p in ports}, clock, config), clock


def candles(start_ms: int, n: int) -> list[MarkKline]:
    return [MarkKline(start_ms + i * MINUTE_MS, D(100), D(101), D(99), D(100)) for i in range(n)]


async def test_poll_fills_cache_and_ages() -> None:
    port = FakePort("kucoin")
    f, clock = feed(port)
    assert f.is_stale("kucoin")  # never loaded
    await f.poll_venue("kucoin")
    assert f.market("kucoin", "ABC") is not None
    assert f.ticker("kucoin", "ABC/USDT:USDT") is not None
    assert f.funding("kucoin", "ABC/USDT:USDT") is not None
    assert port.funding_symbols == [None]  # bulk venue
    assert f.ticker_age_ms("kucoin") == 0
    assert not f.is_stale("kucoin")
    clock.now += 61_000
    assert f.ticker_age_ms("kucoin") == 61_000
    assert f.is_stale("kucoin")
    assert f.funding_age_ms("kucoin", "ABC/USDT:USDT") == 61_000


async def test_cadence_markets_and_funding_not_refetched_every_cycle() -> None:
    port = FakePort("kucoin")
    f, clock = feed(port)
    for _ in range(3):
        await f.poll_venue("kucoin")
        clock.now += 30_000
    assert port.calls["tickers"] == 3
    assert port.calls["markets"] == 1
    assert port.calls["funding"] == 2  # at t=0 and t=60 s
    clock.now += 1_800_000
    await f.poll_venue("kucoin")
    assert port.calls["markets"] == 2


async def test_okx_funding_is_per_watched_symbol() -> None:
    port = FakePort("okx")
    f, clock = feed(port)
    await f.poll_venue("okx")
    assert "funding" not in port.calls  # nothing watched
    f.set_watch("okx", ["ABC/USDT:USDT"])
    clock.now += 61_000
    await f.poll_venue("okx")
    assert port.funding_symbols == [["ABC/USDT:USDT"]]


async def test_rate_limit_pauses_only_that_venue() -> None:
    a, b = FakePort("okx"), FakePort("kucoin")
    f, clock = feed(a, b, rate_limit_backoff_s=60.0)
    a.fail = ExchangeRateLimitError("okx", "429")
    await f.poll_venue("okx")
    await f.poll_venue("kucoin")
    assert f.is_paused("okx")
    assert not f.is_paused("kucoin")
    assert f.counters["rate_limited"] >= 1
    calls_before = dict(a.calls)
    clock.now += 30_000
    await f.poll_venue("okx")  # still paused: no network call
    assert a.calls == calls_before
    await f.poll_venue("kucoin")
    assert b.calls["tickers"] == 2
    a.fail = None
    clock.now += 31_000
    await f.poll_venue("okx")
    assert f.ticker("okx", "ABC/USDT:USDT") is not None
    assert not f.is_paused("okx")


async def test_failures_mark_stale_then_recover() -> None:
    port = FakePort("okx")
    f, clock = feed(port, down_after_failures=2)
    await f.poll_venue("okx")
    port.fail = RuntimeError("boom")
    for _ in range(2):
        clock.now += 30_000
        await f.poll_venue("okx")  # never raises
    assert f.is_stale("okx")
    port.fail = None
    for _ in range(2):
        clock.now += 1_000
        await f.poll_venue("okx")
    assert not f.is_stale("okx")


async def test_basis_sampling_and_drops() -> None:
    port = FakePort("okx")
    f, clock = feed(port, basis_spot_max_age_ms=15_000)
    f.update_spot("binance", {"ABC": (D("101"), T0 - 1_000)})
    await f.poll_venue("okx")
    buf = f.basis.get(("ABC", "binance", "okx"))
    assert buf is not None
    assert len(buf) == 1
    times, values = buf.samples()
    assert times == [T0]
    assert values[0] == round((D("101") - D(100)) / D("100.5") * 10**8)
    # stale spot (older than 15 s vs the perp ticker) is dropped, not stored
    clock.now += 30_000
    await f.poll_venue("okx")
    assert len(buf) == 1
    assert f.counters["basis_dropped"] == 1
    # crossed perp book and non-spot venues are not sampled
    port.bid = D("100")
    clock.now += 30_000
    f.update_spot("binance", {"ABC": (D("101"), clock.now)})
    f.update_spot("gateio", {"ABC": (D("101"), clock.now)})
    await f.poll_venue("okx")
    assert len(buf) == 2
    assert f.basis.get(("ABC", "gateio", "okx")) is None


async def test_klines_incremental_and_coverage() -> None:
    port = FakePort("okx")
    f, clock = feed(port, kline_window_h=1)
    port.klines = candles(T0 - 60 * MINUTE_MS, 30)  # half of the hour
    assert await f.refresh_klines("okx", "ABC/USDT:USDT")
    assert len(f.klines("okx", "ABC/USDT:USDT")) == 30
    assert f.kline_coverage("okx", "ABC/USDT:USDT") == D("0.5")
    assert port.kline_since[0] == T0 - 60 * MINUTE_MS
    port.klines = candles(T0 - 60 * MINUTE_MS, 60)
    assert await f.refresh_klines("okx", "ABC/USDT:USDT")  # within refresh interval: cached
    assert port.calls["klines"] == 1
    assert await f.refresh_klines("okx", "ABC/USDT:USDT", force=True)
    assert port.kline_since[1] == T0 - 31 * MINUTE_MS  # newest cached candle is re-fetched
    assert f.kline_coverage("okx", "ABC/USDT:USDT") == D(1)
    clock.now += 30 * MINUTE_MS  # candles roll out of the window
    assert f.kline_coverage("okx", "ABC/USDT:USDT") == D("0.5")
    assert f.kline_coverage("okx", "NOPE") == D(0)


async def test_prefetch_loaded_by_the_loop_and_tiers() -> None:
    port = FakePort("okx")
    f, _ = feed(port, kline_window_h=1)
    port.klines = candles(T0 - 60 * MINUTE_MS, 60)
    f.request_prefetch("okx", "ABC/USDT:USDT")
    assert not f.tiers_ready("okx", "ABC/USDT:USDT")
    await f.poll_venue("okx")
    assert f.kline_coverage("okx", "ABC/USDT:USDT") == D(1)
    assert f.tiers_ready("okx", "ABC/USDT:USDT")
    await f.poll_venue("okx")
    assert port.calls["klines"] == 1  # prefetch served once


async def test_tiers_not_public_stay_not_ready() -> None:
    port = FakePort("binance")
    port.tier_result = None
    f, _ = feed(port)
    assert await f.refresh_tiers("binance", "ABC/USDT:USDT")
    assert f.tiers("binance", "ABC/USDT:USDT") is not None
    assert not f.tiers_ready("binance", "ABC/USDT:USDT")


async def test_open_positions_klines_refreshed_on_liq_cadence() -> None:
    port = FakePort("okx")
    f, clock = feed(port, liq_check_s=300.0)
    f.set_open("okx", ["ABC/USDT:USDT"])
    await f.poll_venue("okx")
    clock.now += 30_000
    await f.poll_venue("okx")
    assert port.calls["klines"] == 1
    clock.now += 300_000
    await f.poll_venue("okx")
    assert port.calls["klines"] == 2


async def test_run_stops_promptly_even_with_a_hanging_port() -> None:
    hanging, ok = FakePort("okx"), FakePort("kucoin")
    hanging.hang = True
    f, _ = feed(hanging, ok, ticker_interval_s=0.01, call_timeout_s=3600.0)
    stop = asyncio.Event()
    task = asyncio.create_task(f.run(stop))
    await asyncio.sleep(0.05)
    assert f.ticker("kucoin", "ABC/USDT:USDT") is not None  # healthy venue unaffected
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)


async def test_run_cancellation_does_not_hang() -> None:
    port = FakePort("okx")
    port.hang = True
    f, _ = feed(port, ticker_interval_s=0.01, call_timeout_s=3600.0)
    task = asyncio.create_task(f.run(asyncio.Event()))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)


async def test_loop_never_raises_on_port_errors() -> None:
    port = FakePort("okx")
    port.fail = RuntimeError("boom")
    f, _ = feed(port, ticker_interval_s=0.01)
    stop = asyncio.Event()
    task = asyncio.create_task(f.run(stop))
    await asyncio.sleep(0.05)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert f.counters["errors"] >= 1


async def test_unexpected_exception_in_poll_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    port = FakePort("okx")
    f, _ = feed(port, ticker_interval_s=0.01)

    async def broken(venue: str) -> None:
        raise ValueError("bug")

    monkeypatch.setattr(f, "poll_venue", broken)
    stop = asyncio.Event()
    task = asyncio.create_task(f.run(stop))
    await asyncio.sleep(0.05)
    assert not task.done()
    assert f.counters["loop_errors"] >= 1
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)


def test_unknown_venue_inputs_are_ignored() -> None:
    f, _ = feed(FakePort("okx"))
    f.set_watch("nope", ["x"])
    f.set_open("nope", ["x"])
    f.request_prefetch("nope", "x")
    assert f.venues == ("okx",)
    assert f.market("nope", "ABC") is None
    assert f.ticker_age_ms("nope") is None
    assert f.tiers("nope", "x") is None


def test_hedge_venues_of() -> None:
    assert hedge_venues_of({"a": ("okx", "kucoin"), "b": ("binance", "okx", "kucoin")}) == (
        "binance",
        "kucoin",
        "okx",
    )
