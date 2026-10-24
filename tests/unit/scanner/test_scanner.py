import asyncio
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

import pytest

from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.errors import (
    ExchangeAuthError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from nexus.domain.events import (
    AlertContext,
    EpisodeClosed,
    ExchangeDown,
    ExchangeRecovered,
    RoutesQuarantined,
    ScannerStarted,
    ScannerStopped,
)
from nexus.domain.models import (
    AssetTransferInfo,
    MarketInfo,
    NetworkInfo,
    OrderBook,
    PriceLevel,
    Ticker,
)
from nexus.domain.spread import EvaluationStatus, TransferStatus
from nexus.engine.candidates import CandidateFilter, CandidateFinder
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.interfaces.market_data import ITradingFeeSource
from nexus.interfaces.repositories import ExchangeMetadataStats, IMetadataStatsRepository
from nexus.scanner import service
from nexus.scanner.capstats import CapStatsBuffer
from nexus.scanner.episodes import EpisodeTracker
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.paper import PaperBook, PaperTrader
from nexus.scanner.quarantine import QuarantineManager
from nexus.scanner.service import Repositories, Scanner, ScannerConfig
from nexus.scanner.streams import OrderBookStreams
from nexus.scanner.universe import UniverseFilter
from nexus.simulation.portfolio import PaperConfig, RebalanceStatus, SkipReason
from tests.fakes import (
    FakeExchange,
    ManualClock,
    MemoryCooldowns,
    MemoryEpisodes,
    MemoryHeartbeat,
    MemoryPaper,
    MemoryQuarantine,
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
        self,
        *,
        fee_lookup: bool = False,
        streaming: bool = False,
        require_verified: bool = False,
        episodes: bool = False,
        quarantine: bool = False,
        paper: bool = False,
        paper_sets: dict[str, frozenset[str] | None] | None = None,
        max_candidates: int = 10,
        paper_config: PaperConfig | None = None,
    ) -> None:
        self.paper_config = paper_config or _paper_config()
        self.clock = ManualClock()
        self.a = (FeeLookupExchange if fee_lookup else FakeExchange)("a", self.clock)
        self.streaming_b = StreamingExchange("b", self.clock)
        self.b: FakeExchange = self.streaming_b if streaming else FakeExchange("b", self.clock)
        self.c = FakeExchange("c", self.clock)
        self.repos = MemoryRepos()
        self.cooldowns = MemoryCooldowns()
        self.heartbeat = MemoryHeartbeat()
        self.dispatcher = RecordingDispatcher()
        self.quarantine_store = MemoryQuarantine(self.clock)
        self.quarantine = (
            QuarantineManager(
                self.quarantine_store,
                self.quarantine_store,
                persist_ms=15 * 60_000,
                ttl_ms=24 * 3_600_000,
                clock=self.clock,
            )
            if quarantine
            else None
        )
        self.paper_repo = MemoryPaper()
        self.episode_repo = MemoryEpisodes()
        self.episodes = (
            EpisodeTracker(self.episode_repo, close_gap_ms=60_000, clock=self.clock)
            if episodes
            else None
        )
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
                max_candidates_per_sweep=max_candidates,
                max_concurrent_requests_per_exchange=2,
                snapshot_top_k=5,
                heartbeat_ttl_s=60,
                alert_cooldown_s=600,
                book_deadline_s=2.0,
                latency_check_ms=0,
            ),
            clock=self.clock,
            streams=self.streams,
            episodes=self.episodes,
            quarantine=self.quarantine,
            paper=self._paper_book(spread, paper_sets) if paper else None,
        )

    def _paper_book(
        self, spread: EstimatorConfig, sets: dict[str, frozenset[str] | None] | None
    ) -> PaperBook:
        estimator = NetSpreadEstimator(replace(spread, include_transfer_cost=False), self.clock)
        return PaperBook(
            {
                name: PaperTrader(
                    self.paper_config,
                    self.paper_repo,
                    estimator,
                    self.clock,
                    portfolio_id=name,
                    venues=venues,
                )
                for name, venues in (sets or {"all": None}).items()
            },
            CapStatsBuffer(self.paper_repo),
        )


def _paper_config() -> PaperConfig:
    return PaperConfig(
        usdt_per_exchange=D(1000),
        coin_per_route_usd=D(1000),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=30 * 60_000,
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

    async def broken(evaluation_id: int, context: object = None) -> None:
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


# ------------------------------------------------------------------ episodes


def _episode_harness(**kwargs: Any) -> Harness:
    h = Harness(episodes=True, **kwargs)
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    return h


async def _settle(h: Harness) -> None:
    for _ in range(20):
        await asyncio.sleep(0)
    await asyncio.gather(*h.scanner._latency_checks)


async def test_sweep_links_evaluations_to_episodes_and_checks_latency() -> None:
    h = _episode_harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    (episode,) = h.episode_repo.rows.values()
    assert episode.route_key == "ABC/USDT|a>b"
    assert episode.survived_latency is True  # REST books still show the spread
    linked = {i for i, e in h.repos.evaluation_episodes.items() if e == episode.id}
    assert linked
    assert all(h.repos.evaluations[i].meets_thresholds for i in linked)
    unlinked = [i for i, e in h.repos.evaluation_episodes.items() if e is None]
    assert all(not h.repos.evaluations[i].meets_thresholds for i in unlinked)
    h.clock.now += 10_000
    await h.scanner.sweep()
    assert h.episode_repo.rows[episode.id].evaluations == 2  # type: ignore[index]


async def test_vanished_spread_fails_latency_check_and_closes_after_gap() -> None:
    h = _episode_harness()
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    h.b.book_quotes["ABC/USDT"] = ("100", "100.1")  # gone before the re-check
    await _settle(h)
    (episode,) = h.episode_repo.rows.values()
    assert episode.survived_latency is False
    h.clock.now += 60_000
    await h.scanner.sweep()  # no qualifying evaluation any more
    closed = h.episode_repo.rows[1]
    assert closed.close_reason is not None
    assert closed.close_reason.value == "gap"


async def test_unverified_routes_open_episodes_without_alerting() -> None:
    h = _episode_harness(require_verified=True)
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 0
    (episode,) = h.episode_repo.rows.values()
    assert episode.transfer_status.value == "unknown"


async def test_episode_storage_failure_does_not_block_alerts() -> None:
    h = _episode_harness()

    async def broken(*_: object) -> None:
        raise ConnectionError("db down")

    h.episode_repo.open = broken  # type: ignore[assignment,method-assign]
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 1
    assert result.evaluations >= 1
    assert all(e is None for e in h.repos.evaluation_episodes.values())


async def test_run_resumes_episodes_on_start() -> None:
    h = _episode_harness()
    stale = OpportunityEpisode(
        symbol="OLD/USDT",
        buy_exchange="a",
        sell_exchange="b",
        opened_at_ms=h.clock.now - 600_000,
        last_seen_at_ms=h.clock.now - 300_000,
        first_net_usd=D(6),
        peak_net_usd=D(6),
        last_net_usd=D(6),
        peak_net_pct=D("0.6"),
        evaluations=3,
        transfer_status=TransferStatus.VERIFIED,
        transfer_network="TRC20",
    )
    await h.episode_repo.open(stale)
    stop = asyncio.Event()

    async def beat_then_stop(service: str, ttl_s: int) -> None:
        stop.set()

    h.heartbeat.beat = beat_then_stop  # type: ignore[method-assign]
    await asyncio.wait_for(h.scanner.run(stop), timeout=5)
    assert h.episode_repo.rows[1].close_reason is not None
    assert h.episode_repo.rows[1].close_reason.value == "restart"


async def test_one_alert_per_episode_realert_on_growth_and_close_message() -> None:
    h = _episode_harness()
    await h.scanner.refresh_metadata()
    first = await h.scanner.sweep()
    assert first.alerts == 1
    assert h.dispatcher.contexts[-1] == AlertContext(episode_id=1, realert=0)

    h.cooldowns.active.discard("alert:ABC/USDT|a>b")  # even without the floor:
    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 0  # same episode, no growth -> no alert

    h.b.quote("ABC/USDT", "101.6", "101.7")  # net grows well above +50 %
    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 1
    context = h.dispatcher.contexts[-1]
    assert context is not None
    assert (context.episode_id, context.realert) == (1, 1)
    assert context.previous_net_usd is not None
    assert D(context.previous_net_usd) == h.episode_repo.rows[1].first_net_usd

    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 0  # baseline moved up with the re-alert

    h.b.quote("ABC/USDT", "100", "100.1")  # spread gone
    h.clock.now += 60_000
    await h.scanner.sweep()
    (closed,) = [e for e in h.dispatcher.events if isinstance(e, EpisodeClosed)]
    assert (closed.symbol, closed.reason, closed.realerts, closed.evaluations) == (
        "ABC/USDT",
        "gap",
        1,
        4,
    )
    assert closed.duration_s == 30


async def test_floor_blocks_first_alert_of_a_quickly_reopened_episode() -> None:
    h = _episode_harness()
    await h.scanner.refresh_metadata()
    assert (await h.scanner.sweep()).alerts == 1
    h.b.quote("ABC/USDT", "100", "100.1")
    h.clock.now += 60_000
    await h.scanner.sweep()  # episode 1 closes
    h.b.quote("ABC/USDT", "101", "101.1")
    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 0  # episode 2 opens inside the route floor
    assert 2 in h.episode_repo.rows
    h.cooldowns.active.discard("alert:ABC/USDT|a>b")  # floor expired
    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 1
    assert h.dispatcher.contexts[-1] == AlertContext(episode_id=2, realert=0)


async def test_unalerted_episode_closes_silently() -> None:
    h = _episode_harness(require_verified=True)  # unverified: never alerted
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    h.b.quote("ABC/USDT", "100", "100.1")
    h.clock.now += 60_000
    await h.scanner.sweep()
    assert h.episode_repo.rows[1].close_reason is not None
    assert not [e for e in h.dispatcher.events if isinstance(e, EpisodeClosed)]


async def test_episode_dispatch_failure_releases_dedup_and_floor() -> None:
    h = _episode_harness()
    await h.scanner.refresh_metadata()

    async def broken(evaluation_id: int, context: object = None) -> None:
        raise ConnectionError("broker down")

    h.dispatcher.dispatch_opportunity = broken  # type: ignore[method-assign]
    assert (await h.scanner.sweep()).alerts == 0
    assert not h.cooldowns.active
    assert not h.episode_repo.rows[1].alerted


# ------------------------------------------------------------------ quarantine


def _verified_transfers(h: Harness) -> None:
    for exchange in (h.a, h.b):
        exchange.transfers = {
            "ABC": AssetTransferInfo(
                exchange=exchange.name,
                asset="ABC",
                networks=(NetworkInfo("TRC20", True, True, D("0.001")),),
            )
        }


async def _persist(h: Harness, minutes: int) -> None:
    """Keep the spread alive with a sweep every 50 s (inside the 60 s episode gap)."""
    for _ in range(minutes * 60 // 50 + 1):
        await h.scanner.sweep()
        h.clock.now += 50_000


async def test_persistent_unverified_route_is_quarantined_once() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _persist(h, 15)
    (event,) = [e for e in h.dispatcher.events if isinstance(e, RoutesQuarantined)]
    (quarantined,) = event.routes
    assert (quarantined.symbol, quarantined.reason, event.duration_h) == (
        "ABC/USDT",
        "unverified_persistent",
        24,
    )
    assert h.episode_repo.rows[1].close_reason is not None
    assert h.episode_repo.rows[1].close_reason.value == "quarantined"
    assert len(h.quarantine_store.history) == 1

    books_before = len(h.b.book_calls)
    result = await h.scanner.sweep()
    assert result.quarantined == 1
    assert result.candidates == 0  # the dead route no longer takes a book slot
    assert len(h.b.book_calls) == books_before
    stored = h.repos.evaluations[max(h.repos.evaluations)]
    assert stored.status is EvaluationStatus.QUARANTINED
    h.clock.now += 10_000
    stored_count = len(h.repos.evaluations)
    await h.scanner.sweep()
    assert len(h.repos.evaluations) == stored_count  # parked records: once a minute
    h.clock.now += 60_000
    assert stored.gross_spread_pct is not None
    assert not stored.is_alertable
    assert 2 not in h.episode_repo.rows  # parked routes do not reopen episodes
    await _persist(h, 30)
    assert len([e for e in h.dispatcher.events if isinstance(e, RoutesQuarantined)]) == 1
    assert h.dispatcher.opportunities == []


async def test_verified_persistent_route_is_not_quarantined() -> None:
    h = _episode_harness(quarantine=True)
    _verified_transfers(h)
    await h.scanner.refresh_metadata()
    await _persist(h, 20)
    assert h.quarantine_store.history == []
    assert len(h.episode_repo.rows) == 1  # one long, alerted episode
    assert len(h.dispatcher.opportunities) == 1


async def test_quarantine_expires_after_ttl() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _persist(h, 15)
    assert (await h.scanner.sweep()).quarantined == 1
    h.clock.now += 24 * 3_600_000
    result = await h.scanner.sweep()
    assert (result.quarantined, result.candidates) == (0, 1)


async def test_quarantine_lifts_early_when_transfer_becomes_verified() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _persist(h, 15)
    assert h.quarantine is not None
    assert h.quarantine.active
    _verified_transfers(h)
    await h.scanner.refresh_metadata()
    assert h.quarantine.active == {}
    assert [key for key, _ in h.quarantine_store.lifted] == ["ABC/USDT|a>b"]
    result = await h.scanner.sweep()
    assert result.alerts == 1  # verified now: alertable again


async def test_unavailable_transfer_quarantines_immediately() -> None:
    h = _episode_harness(quarantine=True)
    _verified_transfers(h)
    h.a.transfers = {
        "ABC": AssetTransferInfo(
            exchange="a", asset="ABC", networks=(NetworkInfo("TRC20", False, True, D(1)),)
        )
    }
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    (event,) = [e for e in h.dispatcher.events if isinstance(e, RoutesQuarantined)]
    assert event.routes[0].reason == "transfer_unavailable"
    assert "withdrawals disabled on a" in event.routes[0].note
    assert (await h.scanner.sweep()).quarantined == 1


async def test_quarantine_store_failure_fails_open() -> None:
    h = _episode_harness(quarantine=True)
    _verified_transfers(h)

    async def broken() -> dict[str, object]:
        raise ConnectionError("redis down")

    h.quarantine_store.active = broken  # type: ignore[method-assign,assignment]
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.alerts == 1  # verified route still alerts


def test_manual_symbol_overrides() -> None:
    market = MarketInfo(
        exchange="a", symbol="ABC/USDT", base="ABC", quote="USDT", taker_fee=D("0.001")
    )
    other = replace(market, symbol="XYZ/USDT", base="XYZ")
    usdt = frozenset({"USDT"})
    assert UniverseFilter(quote_assets=usdt).accepts(market)
    only_abc = UniverseFilter(quote_assets=usdt, whitelist=frozenset({"ABC/USDT"}))
    assert only_abc.accepts(market)
    assert not only_abc.accepts(other)  # whitelist: scan ONLY the listed symbols
    both = UniverseFilter(
        quote_assets=usdt, whitelist=frozenset({"ABC/USDT"}), blacklist=frozenset({"ABC/USDT"})
    )
    assert not both.accepts(market)  # blacklist wins over whitelist


async def test_verified_episode_is_not_quarantined_on_a_metadata_glitch() -> None:
    h = _episode_harness(quarantine=True)
    _verified_transfers(h)
    await h.scanner.refresh_metadata()
    await _persist(h, 20)  # long verified episode
    h.a.transfers = None  # one refresh loses the transfer data -> UNKNOWN from now on
    await h.scanner.refresh_metadata()
    await _persist(h, 10)
    assert h.quarantine_store.history == []  # unverified for 10 min only
    await _persist(h, 6)
    (quarantine,) = h.quarantine_store.history
    assert quarantine.note == "spread seen 15 min in 1 episode(s) with transfer unknown"


async def test_requarantine_of_a_dead_route_is_announced_weekly_at_most() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _persist(h, 15)
    h.clock.now += 24 * 3_600_000  # quarantine expired; the route is still dead
    await _persist(h, 16)
    assert len(h.quarantine_store.history) == 2
    assert len([e for e in h.dispatcher.events if isinstance(e, RoutesQuarantined)]) == 1


async def test_quarantines_of_one_sweep_share_one_message() -> None:
    h = _episode_harness(quarantine=True)
    blocked = {
        "ABC": AssetTransferInfo(exchange="a", asset="ABC", withdraw_enabled=False),
        "DEF": AssetTransferInfo(exchange="a", asset="DEF", withdraw_enabled=False),
    }
    h.a.quote("DEF/USDT", "9.99", "10")
    h.b.quote("DEF/USDT", "10.1", "10.11")
    h.a.transfers = blocked
    h.b.transfers = {
        asset: AssetTransferInfo(
            exchange="b", asset=asset, networks=(NetworkInfo("TRC20", True, True, D(0)),)
        )
        for asset in ("ABC", "DEF")
    }
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    (event,) = [e for e in h.dispatcher.events if isinstance(e, RoutesQuarantined)]
    assert sorted(r.symbol for r in event.routes) == ["ABC/USDT", "DEF/USDT"]


async def test_stale_snapshot_expires_while_the_store_is_down() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _persist(h, 15)
    assert (await h.scanner.sweep()).quarantined == 1

    async def broken() -> dict[str, object]:
        raise ConnectionError("redis down")

    h.quarantine_store.active = broken  # type: ignore[method-assign,assignment]
    assert (await h.scanner.sweep()).quarantined == 1  # last snapshot still applies
    h.clock.now += 24 * 3_600_000
    assert (await h.scanner.sweep()).quarantined == 0  # but it expires on the clock


# ------------------------------------------------------------------ paper trading


def _usdt_and_abc_transfers(h: Harness, *, usdt_verified: bool) -> None:
    for exchange in (h.a, h.b):
        networks = (NetworkInfo("TRC20", True, True, D(1)),) if usdt_verified else ()
        exchange.transfers = {
            "ABC": AssetTransferInfo(
                exchange=exchange.name,
                asset="ABC",
                networks=(NetworkInfo("TRC20", True, True, D("0.001")),),
            ),
            "USDT": AssetTransferInfo(exchange=exchange.name, asset="USDT", networks=networks),
        }


async def test_alert_is_paper_traded_after_latency_and_rebalanced() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=True)
    await h.scanner.refresh_metadata()
    assert (await h.scanner.sweep()).alerts == 1
    await _settle(h)
    (outcome, episode_id) = h.paper_repo.trades[0]
    assert outcome.executed
    assert episode_id == 1
    assert outcome.breakdown is not None
    assert outcome.breakdown.transfer_fee_usd == 0  # no per-trade transfer: rebalancing
    portfolio = h.scanner._paper.trader().portfolio  # type: ignore[union-attr]
    # The whole USDT on A and the coin on B were used: both sides are rebalanced virtually.
    routes = {
        (r.asset, r.from_exchange, r.to_exchange): r for r in h.paper_repo.rebalances.values()
    }
    assert set(routes) == {("USDT", "b", "a"), ("ABC", "a", "b")}
    assert routes[("USDT", "b", "a")].fee == D(1)
    assert routes[("ABC", "a", "b")].fee == D("0.001")
    assert all(r.status is RebalanceStatus.IN_FLIGHT for r in routes.values())
    valuation = portfolio.valuation()
    assert valuation.realized == outcome.net_usd
    assert valuation.rebalance_costs == D(1) + D("0.001") * portfolio.prices["ABC"]
    h.clock.now += 30 * 60_000
    await h.scanner.sweep()  # transfers arrive
    assert all(r.status is RebalanceStatus.COMPLETED for r in h.paper_repo.rebalances.values())
    assert portfolio.balance("a", "USDT") > D(900)
    assert portfolio.in_flight == []


async def test_rebalance_without_verified_network_is_blocked_and_reported() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=False)
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    blocked = [r for r in h.paper_repo.rebalances.values() if r.asset == "USDT"]
    assert [r.status for r in blocked] == [RebalanceStatus.BLOCKED]


async def test_paper_storage_failure_does_not_break_the_sweep() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=True)
    await h.scanner.refresh_metadata()
    h.paper_repo.fail_next = True
    assert (await h.scanner.sweep()).alerts == 1
    await _settle(h)  # the trade's commit failed: logged, scanner keeps running
    h.clock.now += 10_000
    await h.scanner.sweep()


async def test_paper_portfolio_resumes_after_restart() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=True)
    await h.scanner.refresh_metadata()
    await h.scanner._paper.start()  # type: ignore[union-attr]  # registers the run
    await h.scanner.sweep()
    await _settle(h)
    before = h.scanner._paper.trader().portfolio  # type: ignore[union-attr]
    resumed = PaperTrader(
        before.config,
        h.paper_repo,
        NetSpreadEstimator(
            replace(h.scanner._estimator.config, include_transfer_cost=False), h.clock
        ),
        h.clock,
    )
    await resumed.start()
    assert resumed.portfolio.balances == before.balances
    assert resumed.portfolio.seeds == before.seeds
    assert len(resumed.portfolio.in_flight) == 2
    assert resumed.portfolio.valuation() == before.valuation()


async def test_failed_commit_rolls_back_memory() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=True)
    await h.scanner.refresh_metadata()
    h.paper_repo.fail_next = True
    await h.scanner.sweep()
    await _settle(h)
    portfolio = h.scanner._paper.trader().portfolio  # type: ignore[union-attr]
    assert portfolio.realized == 0  # the trade was not persisted -> not kept in memory
    assert portfolio.in_flight == []
    assert h.paper_repo.trades == []


async def test_route_is_paper_traded_once_per_minute() -> None:
    h = _episode_harness(paper=True)
    _usdt_and_abc_transfers(h, usdt_verified=True)
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    h.b.quote("ABC/USDT", "101.6", "101.7")  # +50 % growth -> re-alert 10 s later
    h.clock.now += 10_000
    assert (await h.scanner.sweep()).alerts == 1
    await _settle(h)
    reasons = [t.skip_reason for t, _ in h.paper_repo.trades]
    assert reasons == [None, SkipReason.RECENT_FILL]


async def test_resume_failure_disables_paper_trading() -> None:
    h = _episode_harness(paper=True)

    async def broken(*args: object) -> None:
        raise ConnectionError("db down")

    h.paper_repo.ensure_run = broken  # type: ignore[method-assign,assignment]
    stop = asyncio.Event()

    async def beat_then_stop(service: str, ttl_s: int) -> None:
        stop.set()

    h.heartbeat.beat = beat_then_stop  # type: ignore[method-assign]
    await asyncio.wait_for(h.scanner.run(stop), timeout=5)
    assert h.scanner._paper is None
    assert h.paper_repo.trades == []


async def test_metadata_refresh_records_coverage_stats() -> None:
    recorded: list[tuple[int, list[ExchangeMetadataStats]]] = []

    class _Stats(IMetadataStatsRepository):
        async def record(self, at_ms: int, stats: Sequence[ExchangeMetadataStats]) -> None:
            recorded.append((at_ms, list(stats)))

    h = Harness()
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    h.scanner._repos = replace(h.scanner._repos, metadata_stats=_Stats())
    await h.scanner.refresh_metadata()
    (at_ms, stats) = recorded[0]
    assert at_ms == h.clock.now
    assert [(s.exchange, s.markets, s.transfer_coverage_pct) for s in stats] == [
        ("a", 1, 0),
        ("b", 1, 0),
        ("c", 0, None),
    ]


async def test_sweep_reports_coverage_metrics(h: Harness) -> None:
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    assert result.evaluated_symbols == 1
    assert result.routes == sum(result.routes_by_pair.values())
    assert result.routes_by_pair["a>b"] == 1
    assert all(">" in pair for pair in result.routes_by_pair)


async def _flap(h: Harness, times: int, *, on_s: int = 30, off_s: int = 400) -> None:
    """A spread that appears for ``on_s`` and vanishes for ``off_s`` (closing the episode)."""
    for _ in range(times):
        h.b.quote("ABC/USDT", "101", "101.1")
        await h.scanner.sweep()
        h.clock.now += on_s * 1000
        await h.scanner.sweep()
        h.b.quote("ABC/USDT", "100", "100.1")
        h.clock.now += off_s * 1000
        await h.scanner.sweep()


async def test_flapping_unverified_route_is_quarantined_by_recurrence() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _flap(h, 4)
    assert h.quarantine_store.history == []  # 4 short episodes: not yet
    await _flap(h, 1)
    (quarantine,) = h.quarantine_store.history
    assert quarantine.note == "spread seen 2 min in 5 episode(s) with transfer unknown"
    assert len(h.episode_repo.rows) == 5


async def test_old_unverified_episodes_leave_the_window() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _flap(h, 4)
    h.clock.now += 6 * 3_600_000  # the window forgets them
    await _flap(h, 1)
    assert h.quarantine_store.history == []


async def test_verified_flapping_route_is_never_quarantined() -> None:
    h = _episode_harness(quarantine=True)
    _verified_transfers(h)
    await h.scanner.refresh_metadata()
    await _flap(h, 8)
    assert h.quarantine_store.history == []


async def test_lifted_route_is_not_requarantined_from_old_history() -> None:
    h = _episode_harness(require_verified=True, quarantine=True)
    await h.scanner.refresh_metadata()
    await _flap(h, 5)
    assert len(h.quarantine_store.history) == 1
    _verified_transfers(h)
    await h.scanner.refresh_metadata()  # lifted: the transfer path is verified now
    assert h.quarantine is not None
    assert h.quarantine.active == {}
    h.b.quote("ABC/USDT", "100", "100.1")  # no spread: no fresh evidence either way
    await h.scanner.sweep()
    await h.scanner.sweep()
    assert len(h.quarantine_store.history) == 1
    assert h.quarantine.active == {}
