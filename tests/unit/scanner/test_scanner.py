import asyncio
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.errors import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from nexus.domain.events import ExchangeDown, ExchangeRecovered, ScannerStarted, ScannerStopped
from nexus.domain.models import (
    AssetTransferInfo,
    MarketInfo,
    NetworkInfo,
    OrderBook,
    PriceLevel,
    Ticker,
)
from nexus.domain.spread import EvaluationStatus
from nexus.engine.candidates import CandidateFilter, CandidateFinder
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.interfaces.market_data import ITradingFeeSource
from nexus.scanner import service
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.service import Repositories, Scanner, ScannerConfig
from nexus.scanner.streams import OrderBookStreams
from nexus.scanner.universe import UniverseFilter
from tests.fakes import (
    FakeExchange,
    ManualClock,
    MemoryCooldowns,
    MemoryHeartbeat,
    MemoryRepos,
    RecordingDispatcher,
)
from tests.unit.scanner.test_streams import StreamingExchange


class FeeLookupExchange(FakeExchange, ITradingFeeSource):
    """Publishes default fees in metadata; the account fee needs a per-symbol lookup."""

    def __init__(self, name: str, clock: ManualClock) -> None:
        super().__init__(name, clock)
        self.account_fee: D | None = D("0.0005")
        self.fee_errors: list[ExchangeError] = []
        self.fee_calls: list[str] = []
        self.fee_delay_s = 0.0

    async def load_markets(self) -> Sequence[MarketInfo]:
        return [replace(m, taker_fee_is_default=True) for m in await super().load_markets()]

    async def fetch_taker_fee(self, symbol: str) -> D | None:
        self.fee_calls.append(symbol)
        if self.fee_delay_s:
            await asyncio.sleep(self.fee_delay_s)
        if self.fee_errors:
            raise self.fee_errors.pop(0)
        return self.account_fee


class Harness:
    def __init__(
        self, *, fee_lookup: bool = False, streaming: bool = False, require_verified: bool = False
    ) -> None:
        self.clock = ManualClock()
        self.a = (FeeLookupExchange if fee_lookup else FakeExchange)("a", self.clock)
        self.streaming_b = StreamingExchange("b", self.clock)
        self.b: FakeExchange = self.streaming_b if streaming else FakeExchange("b", self.clock)
        self.c = FakeExchange("c", self.clock)
        self.repos = MemoryRepos()
        self.cooldowns = MemoryCooldowns()
        self.heartbeat = MemoryHeartbeat()
        self.dispatcher = RecordingDispatcher()
        self.streams = (
            OrderBookStreams(
                {"b": self.b},
                depth=20,
                max_streams=10,
                hot_ttl_ms=60_000,
                max_book_age_ms=1_000,
                clock=self.clock,
            )
            if streaming
            else None
        )
        spread = EstimatorConfig(
            min_net_profit_pct=D("0.3"),
            min_net_profit_usd=D(5),
            reference_notional_usd=D(1000),
            max_orderbook_age_ms=5_000,
            max_book_skew_ms=3_000,
            max_gross_spread_pct=D(20),
            include_transfer_cost=True,
            require_verified_transfer=require_verified,
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
            streams=self.streams,
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


async def test_transfer_coverage_per_exchange(h: Harness) -> None:
    h.a.transfers = {
        "ABC": AssetTransferInfo(
            exchange="a",
            asset="ABC",
            networks=(NetworkInfo("ERC20", True, False, D(1)),),
        )
    }
    h.b.transfers = {
        "ABC": AssetTransferInfo(
            exchange="b", asset="ABC", networks=(NetworkInfo("ERC20", None, True, D(1)),)
        )
    }
    universe = await h.scanner.refresh_metadata()
    assert universe.transfer_coverage_pct("a") == 100
    assert universe.transfer_coverage_pct("b") == 0  # withdraw flag unreported
    assert universe.transfer_coverage_pct("c") == 0  # no metadata at all
    assert universe.transfer_coverage_pct("unknown") is None
    h.b.transfers = {"ABC": AssetTransferInfo(exchange="b", asset="ABC", withdraw_enabled=False)}
    assert (await h.scanner.refresh_metadata()).transfer_coverage_pct("b") == 100


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
    assert {e.transfer_coverage_pct for e in started.exchanges} == {0}
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


def _fee_harness() -> tuple[Harness, FeeLookupExchange]:
    harness = Harness(fee_lookup=True)
    assert isinstance(harness.a, FeeLookupExchange)
    harness.a.quote("ABC/USDT", "99.9", "100")
    harness.b.quote("ABC/USDT", "101", "101.1")
    return harness, harness.a


async def test_account_fee_looked_up_once_for_candidates() -> None:
    h, a = _fee_harness()
    await h.scanner.refresh_metadata()
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee_is_default
    await h.scanner.sweep()
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee == D("0.0005")
    assert not market.taker_fee_is_default
    evaluation = next(iter(h.repos.evaluations.values()))
    assert not evaluation.fees_estimated  # both legs priced with account fees
    await h.scanner.sweep()
    await h.scanner.refresh_metadata()  # refresh keeps the looked-up fee
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee == D("0.0005")
    await h.scanner.sweep()
    assert a.fee_calls == ["ABC/USDT"]


async def test_failed_fee_lookup_retried_and_rate_limit_pauses() -> None:
    h, a = _fee_harness()
    a.fee_errors = [ExchangeRateLimitError("a", "429")]
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee_is_default
    assert h.scanner._health.is_paused("a", h.clock.now)
    h.clock.now += 61_000
    await h.scanner.sweep()
    assert a.fee_calls == ["ABC/USDT", "ABC/USDT"]
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert not market.taker_fee_is_default


async def test_unavailable_fee_kept_as_estimate_without_retry() -> None:
    h, a = _fee_harness()
    a.account_fee = None
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await h.scanner.sweep()
    assert a.fee_calls == ["ABC/USDT"]
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee_is_default


async def test_no_fee_lookup_without_credentials() -> None:
    h, a = _fee_harness()
    h.scanner._authenticated["a"] = False
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    assert a.fee_calls == []


async def test_account_fee_expires_and_is_looked_up_again() -> None:
    h, a = _fee_harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    a.account_fee = D("0.0007")
    h.clock.now += service.FEE_CACHE_TTL_MS
    await h.scanner.refresh_metadata()  # expired fee dropped -> default again
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee_is_default
    await h.scanner.sweep()
    market = h.scanner.universe.market("a", "ABC/USDT")
    assert market is not None
    assert market.taker_fee == D("0.0007")
    assert a.fee_calls == ["ABC/USDT", "ABC/USDT"]


async def test_permanent_fee_error_not_retried() -> None:
    h, a = _fee_harness()
    a.fee_errors = [ExchangeAuthError("a", "no permission")]
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await h.scanner.sweep()
    assert a.fee_calls == ["ABC/USDT"]


async def test_transient_fee_errors_give_up_after_max_attempts() -> None:
    h, a = _fee_harness()
    a.fee_errors = [ExchangeUnavailableError("a", "502")] * service.FEE_LOOKUP_MAX_ATTEMPTS
    await h.scanner.refresh_metadata()
    for _ in range(service.FEE_LOOKUP_MAX_ATTEMPTS + 2):
        await h.scanner.sweep()
    assert len(a.fee_calls) == service.FEE_LOOKUP_MAX_ATTEMPTS


async def test_slow_fee_lookup_does_not_block_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "FEE_LOOKUP_TIMEOUT_S", 0.05)
    h, a = _fee_harness()
    a.fee_delay_s = 1.0
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.evaluations == 1
    assert result.timed_out == 0
    evaluation = next(iter(h.repos.evaluations.values()))
    assert evaluation.fees_estimated  # default fee kept, flagged as an estimate


async def test_profitable_route_legs_are_streamed() -> None:
    h = Harness(streaming=True)
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    await h.scanner.refresh_metadata()
    first = await h.scanner.sweep()
    assert first.streamed_books == 0
    assert h.streams is not None
    assert h.streams.active == 1  # only b streams; a has no WebSocket support
    book = await h.b.fetch_order_book("ABC/USDT", 20)
    h.streaming_b.push("ABC/USDT", book)
    for _ in range(5):
        await asyncio.sleep(0)
    calls_before = len(h.b.book_calls)
    second = await h.scanner.sweep()
    assert second.streamed_books == 1
    # Alertable on the streamed book -> exactly one REST snapshot to confirm it.
    assert len(h.b.book_calls) == calls_before + 1
    assert second.alerts == 0  # cooldown still active; evaluation still happened
    assert second.evaluations == 1
    await h.streams.close()
    assert h.streaming_b.unwatched == ["ABC/USDT"]


async def test_unverified_route_is_stored_not_alerted_and_not_streamed() -> None:
    h = Harness(streaming=True, require_verified=True)  # fakes publish no transfer metadata
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 0
    assert h.dispatcher.opportunities == []
    stored = next(iter(h.repos.evaluations.values()))
    assert stored.status is EvaluationStatus.TRANSFER_UNVERIFIED
    assert stored.meets_thresholds
    assert h.streams is not None
    assert h.streams.active == 0  # never-alertable routes take no stream slots


async def test_phantom_streamed_level_is_not_alerted() -> None:
    """A desynced WS book shows a profitable bid that the REST snapshot does not confirm."""
    h = Harness(streaming=True)
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()  # positive: b becomes hot
    h.cooldowns.active.clear()
    h.b.book_quotes["ABC/USDT"] = ("100", "100.1")  # real book (REST): no spread any more
    phantom = OrderBook(
        exchange="b",
        symbol="ABC/USDT",
        bids=(PriceLevel(D(101), D(1_000)),),
        asks=(PriceLevel(D("101.1"), D(1_000)),),
        timestamp_ms=h.clock.now,
        received_at_ms=h.clock.now,
    )
    h.streaming_b.push("ABC/USDT", phantom)
    for _ in range(5):
        await asyncio.sleep(0)
    result = await h.scanner.sweep()  # tickers still show the spread
    assert result.streamed_books == 1
    assert result.alerts == 0
    assert result.evaluations == 1  # the stored evaluation is the REST-based one
    stored = h.repos.evaluations[max(h.repos.evaluations)]
    assert not stored.is_alertable
    assert len(h.dispatcher.opportunities) == 1  # only the first, REST-based alert
    assert h.streams is not None
    await h.streams.close()
