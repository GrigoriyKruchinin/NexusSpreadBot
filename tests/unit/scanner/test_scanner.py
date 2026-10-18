import asyncio
from decimal import Decimal as D

import pytest

from nexus.domain.errors import ExchangeRateLimitError, ExchangeUnavailableError
from nexus.domain.events import ExchangeDown, ExchangeRecovered, ScannerStarted, ScannerStopped
from nexus.domain.models import AssetTransferInfo, NetworkInfo, OrderBook, Ticker
from nexus.domain.spread import EvaluationStatus
from nexus.engine.candidates import CandidateFilter, CandidateFinder
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.service import Repositories, Scanner, ScannerConfig
from nexus.scanner.universe import UniverseFilter
from tests.fakes import (
    FakeExchange,
    ManualClock,
    MemoryCooldowns,
    MemoryHeartbeat,
    MemoryRepos,
    RecordingDispatcher,
)


class Harness:
    def __init__(self) -> None:
        self.clock = ManualClock()
        self.a = FakeExchange("a", self.clock)
        self.b = FakeExchange("b", self.clock)
        self.c = FakeExchange("c", self.clock)
        self.repos = MemoryRepos()
        self.cooldowns = MemoryCooldowns()
        self.heartbeat = MemoryHeartbeat()
        self.dispatcher = RecordingDispatcher()
        spread = EstimatorConfig(
            min_net_profit_pct=D("0.3"),
            min_net_profit_usd=D(5),
            reference_notional_usd=D(1000),
            max_orderbook_age_ms=5_000,
            max_book_skew_ms=3_000,
            max_gross_spread_pct=D(20),
            include_transfer_cost=True,
            require_verified_transfer=False,
        )
        self.scanner = Scanner(
            adapters={"a": self.a, "b": self.b, "c": self.c},
            authenticated={"a": True},
            estimator=NetSpreadEstimator(spread, self.clock),
            finder=CandidateFinder(CandidateFilter(D("0.3"), D(20), D(50_000))),
            universe_filter=UniverseFilter(
                quote_assets=frozenset({"USDT"}), blacklist=frozenset({"BAD/USDT"})
            ),
            repositories=Repositories(self.repos, self.repos, self.repos, self.repos),
            cooldowns=self.cooldowns,
            heartbeat=self.heartbeat,
            dispatcher=self.dispatcher,
            health=ExchangeHealthTracker(down_after_failures=2, rate_limit_backoff_ms=60_000),
            config=ScannerConfig(
                ticker_interval_s=0.01,
                metadata_refresh_s=3600,
                orderbook_depth=20,
                max_candidates_per_sweep=10,
                max_concurrent_requests_per_exchange=2,
                snapshot_top_k=5,
                heartbeat_ttl_s=60,
                alert_cooldown_s=600,
                book_deadline_s=2.0,
            ),
            clock=self.clock,
        )


@pytest.fixture
def h() -> Harness:
    harness = Harness()
    harness.a.quote("ABC/USDT", "99.9", "100")  # buy here
    harness.b.quote("ABC/USDT", "101", "101.1")  # sell here: ~0.8 % net
    harness.c.quote("ABC/USDT", "100.05", "101.05")  # no profitable route via c
    harness.a.quote("ONLY/USDT", "1", "1.01")  # single venue -> excluded
    harness.a.quote("BAD/USDT", "1", "1.01")
    harness.b.quote("BAD/USDT", "2", "2.01")  # blacklisted
    harness.a.quote("ABC/BTC", "1", "1.01")
    harness.b.quote("ABC/BTC", "2", "2.01")  # wrong quote
    return harness


async def test_refresh_metadata_builds_common_universe(h: Harness) -> None:
    universe = await h.scanner.refresh_metadata()
    assert universe.common_symbols == {"ABC/USDT"}
    assert {m.exchange for m in h.repos.markets} == {"a", "b", "c"}


async def test_metadata_failure_keeps_previous_markets(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken() -> list[object]:
        raise ExchangeUnavailableError("c", "down")

    h.c.load_markets = broken  # type: ignore[method-assign,assignment]
    universe = await h.scanner.refresh_metadata()
    assert universe.symbols_for("c") == {"ABC/USDT"}


async def test_sweep_alerts_profitable_route_once(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 1
    evaluation = h.repos.evaluations[h.dispatcher.opportunities[0]]
    assert (evaluation.buy_exchange, evaluation.sell_exchange) == ("a", "b")
    assert evaluation.status is EvaluationStatus.PROFITABLE
    assert h.heartbeat.beats == ["scanner"]
    assert h.repos.snapshots
    assert all(name in {"a", "b", "c"} for name, _, ok in h.repos.health if ok)

    second = await h.scanner.sweep()  # cooldown active
    assert second.alerts == 0
    assert len(h.dispatcher.opportunities) == 1
    assert second.evaluations >= 1  # still evaluated and stored


async def test_unavailable_transfer_is_not_alerted(h: Harness) -> None:
    h.a.transfers = {
        "ABC": AssetTransferInfo(
            exchange="a",
            asset="ABC",
            networks=(
                NetworkInfo(
                    "ERC20", withdraw_enabled=False, deposit_enabled=True, withdraw_fee=D(1)
                ),
            ),
        )
    }
    h.b.transfers = {
        "ABC": AssetTransferInfo(
            exchange="b",
            asset="ABC",
            networks=(
                NetworkInfo(
                    "ERC20", withdraw_enabled=True, deposit_enabled=True, withdraw_fee=D(1)
                ),
            ),
        )
    }
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 0
    statuses = {e.status for e in h.repos.evaluations.values()}
    assert EvaluationStatus.TRANSFER_UNAVAILABLE in statuses


async def test_failed_order_book_skips_route(h: Harness) -> None:
    h.b.book_errors["ABC/USDT"] = ExchangeUnavailableError("b", "timeout")
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 0


async def test_exchange_down_and_recovered_events(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    h.c.ticker_errors = [ExchangeUnavailableError("c", "502"), ExchangeUnavailableError("c", "502")]
    await h.scanner.sweep()
    assert not any(isinstance(e, ExchangeDown) for e in h.dispatcher.events)
    await h.scanner.sweep()
    down = [e for e in h.dispatcher.events if isinstance(e, ExchangeDown)]
    assert len(down) == 1
    assert down[0].exchange == "c"
    h.clock.now += 30_000
    await h.scanner.sweep()  # first success: recovery not confirmed yet (hysteresis)
    assert not any(isinstance(e, ExchangeRecovered) for e in h.dispatcher.events)
    await h.scanner.sweep()
    recovered = [e for e in h.dispatcher.events if isinstance(e, ExchangeRecovered)]
    assert recovered == [ExchangeRecovered(exchange="c", downtime_s=30)]


async def test_rate_limited_exchange_is_paused(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    h.c.ticker_errors = [ExchangeRateLimitError("c", "429")]
    await h.scanner.sweep()
    calls = h.c.ticker_calls
    await h.scanner.sweep()
    assert h.c.ticker_calls == calls  # paused
    h.clock.now += 61_000
    await h.scanner.sweep()
    assert h.c.ticker_calls == calls + 1


async def test_run_announces_start_and_stop(h: Harness) -> None:
    stop = asyncio.Event()

    original_beat = h.heartbeat.beat

    async def beat_then_stop(service: str, ttl_s: int) -> None:
        await original_beat(service, ttl_s)
        stop.set()

    h.heartbeat.beat = beat_then_stop  # type: ignore[method-assign]
    await asyncio.wait_for(h.scanner.run(stop), timeout=5)
    started = h.dispatcher.events[0]
    assert isinstance(started, ScannerStarted)
    assert started.common_symbols == 1
    assert started.min_net_profit_pct == "0.3"
    assert [e.name for e in started.exchanges if e.authenticated] == ["a"]
    assert isinstance(h.dispatcher.events[-1], ScannerStopped)


async def test_sweep_failure_does_not_kill_loop(h: Harness) -> None:
    stop = asyncio.Event()
    calls = 0
    original = h.scanner.sweep

    async def flaky() -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        stop.set()
        return await original()

    h.scanner.sweep = flaky  # type: ignore[method-assign,assignment]
    await asyncio.wait_for(h.scanner.run(stop), timeout=5)
    assert calls == 2


def _with_config(h: Harness, **changes: object) -> None:
    from dataclasses import replace as dc_replace

    h.scanner._config = dc_replace(h.scanner._config, **changes)  # type: ignore[arg-type]


async def test_slow_exchange_does_not_block_other_routes(h: Harness) -> None:
    original = h.c.fetch_order_book

    async def hang(symbol: str, depth: int) -> OrderBook:
        await asyncio.sleep(30)
        return await original(symbol, depth)

    h.c.fetch_order_book = hang  # type: ignore[method-assign]
    h.c.quote("ABC/USDT", "101", "101.1")  # c is also a profitable sell venue, but hangs
    await h.scanner.refresh_metadata()
    _with_config(h, book_deadline_s=0.2)
    result = await h.scanner.sweep()
    assert result.alerts == 1  # a>b is still alerted
    assert result.timed_out >= 1


async def test_dispatch_failure_releases_cooldown(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken(evaluation_id: int) -> None:
        raise ConnectionError("broker down")

    h.dispatcher.dispatch_opportunity = broken  # type: ignore[method-assign]
    result = await h.scanner.sweep()
    assert result.alerts == 0
    assert not h.cooldowns.active  # released: the next sweep can alert again
    assert h.heartbeat.beats  # the sweep still completed


async def test_no_heartbeat_with_fewer_than_two_live_exchanges(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    h.a.ticker_errors = [ExchangeUnavailableError("a", "x")]
    h.b.ticker_errors = [ExchangeUnavailableError("b", "x")]
    await h.scanner.sweep()
    assert h.heartbeat.beats == []


async def test_book_rate_limit_pauses_without_down_event(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    h.b.book_errors["ABC/USDT"] = ExchangeRateLimitError("b", "429")
    for _ in range(4):
        await h.scanner.sweep()
    assert not any(isinstance(e, ExchangeDown) for e in h.dispatcher.events)


async def test_stop_cancels_inflight_sweep(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    stop = asyncio.Event()

    async def hang(symbols: object) -> dict[str, Ticker]:
        stop.set()
        await asyncio.sleep(60)
        return {}

    h.a.fetch_tickers = hang  # type: ignore[method-assign]
    await asyncio.wait_for(h.scanner.run(stop), timeout=5)
    assert isinstance(h.dispatcher.events[-1], ScannerStopped)
