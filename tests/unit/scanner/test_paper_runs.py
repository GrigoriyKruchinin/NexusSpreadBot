"""B15 round 2: run registry (fresh run on a changed definition), coin slot release,
cap-binding statistics, fail-closed membership and error handling of the shadow book."""

import asyncio
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from structlog.testing import capture_logs

from nexus.domain.spread import TransferQuote, TransferStatus
from nexus.engine.candidates import SetSweepStats
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.interfaces.repositories import (
    CapStatsDelta,
    PaperHolding,
    PortfolioRun,
    RunDefinition,
)
from nexus.scanner.capstats import HOUR_MS, CapStatsBuffer
from nexus.scanner.paper import PaperBook, PaperTrader
from nexus.simulation.portfolio import (
    PaperConfig,
    RebalanceStatus,
    Seed,
    SkipReason,
    allocate_capital,
)
from tests.fakes import ManualClock, MemoryPaper, PaperData
from tests.unit.scanner.test_scanner import Harness, _settle

ALL = frozenset({"a", "b", "c"})
AB = frozenset({"a", "b"})
UNKNOWN = TransferQuote(TransferStatus.UNKNOWN)


def _config(venues: int, capital: str = "10000") -> PaperConfig:
    usdt, budget = allocate_capital(D(capital), venues, D(50))
    return PaperConfig(
        usdt_per_exchange=usdt,
        coin_per_route_usd=min(D(250), budget),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=30 * 60_000,
        coin_budget_per_venue_usd=budget,
    )


def _trader(
    repo: MemoryPaper, pid: str, venues: frozenset[str], clock: ManualClock, capital: str = "10000"
) -> PaperTrader:
    estimator = NetSpreadEstimator(
        EstimatorConfig(
            min_net_profit_pct=D("0.3"),
            min_net_profit_usd=D(5),
            reference_notional_usd=D(1000),
            max_orderbook_age_ms=5_000,
            max_book_skew_ms=3_000,
            max_gross_spread_pct=D(20),
            include_transfer_cost=False,
            require_verified_transfer=False,
        ),
        clock,
    )
    return PaperTrader(
        _config(len(venues), capital), repo, estimator, clock, portfolio_id=pid, venues=venues
    )


def _legacy_state(repo: MemoryPaper, at_ms: int) -> None:
    """Pre-B15 'all' history: 1000 USDT per venue, 1000 USD coin seed, a legacy run."""
    legacy = RunDefinition((), D(0), "legacy")
    repo.runs["all"] = [PortfolioRun("all", 1, at_ms, legacy)]
    repo._next_run_id = 1
    data = repo.data["all"]
    data.snapshots.append(
        (
            at_ms + 1,
            [
                PaperHolding("a", "USDT", D(900), Seed(D(1000), D(1)), D(1)),
                PaperHolding("b", "ABC", D(7), Seed(D(10), D(100)), D(100)),
            ],
        )
    )


# ------------------------------------------------------------------ run registry (A)


async def test_legacy_all_state_starts_a_fresh_run_with_equal_capital() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    _legacy_state(repo, clock.now - 1000)
    traders = {
        "all": _trader(repo, "all", ALL, clock),
        "ab": _trader(repo, "ab", AB, clock),
    }
    book = PaperBook(traders)
    await book.start()
    for trader in traders.values():
        assert trader.run is not None
        assert trader.run.created
        assert trader.portfolio.balances == {}
        assert trader.portfolio.seeds == {}
        assert abs(trader.run.definition.capital_usd - D(10_000)) < D("1e-20")
    assert traders["all"].run.run_id == 2  # type: ignore[union-attr]  # after the legacy run
    assert traders["all"].run.started_at_ms == clock.now  # type: ignore[union-attr]
    assert repo.data["all"].snapshots  # old rows are kept, only never restored


async def test_same_definition_resumes_the_run_and_its_state() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    first = _trader(repo, "ab", AB, clock)
    await first.start()
    assert first.run is not None
    assert first.run.created
    started = first.run.started_at_ms
    clock.now += 60_000
    repo.data.setdefault("ab", PaperData()).snapshots.append(
        (clock.now, [PaperHolding("a", "USDT", D(5), Seed(D(100), D(1)), D(1))])
    )
    second = _trader(repo, "ab", AB, clock)
    await second.start()
    assert second.run is not None
    assert not second.run.created
    assert second.run.run_id == first.run.run_id
    assert second.run.started_at_ms == started
    assert second.portfolio.balance("a", "USDT") == D(5)


@pytest.mark.parametrize("change", ["capital", "venues"])
async def test_changed_definition_starts_a_new_run_under_the_same_name(change: str) -> None:
    clock, repo = ManualClock(), MemoryPaper()
    old = _trader(repo, "ab", AB, clock)
    await old.start()
    clock.now += 60_000
    repo.data.setdefault("ab", PaperData()).snapshots.append(
        (clock.now, [PaperHolding("a", "USDT", D(5), Seed(D(100), D(1)), D(1))])
    )
    clock.now += 60_000
    new = (
        _trader(repo, "ab", AB, clock, capital="5000")
        if change == "capital"
        else _trader(repo, "ab", ALL, clock)
    )
    await new.start()
    assert new.run is not None
    assert new.run.created
    assert old.run is not None
    assert new.run.run_id == old.run.run_id + 1
    assert new.run.started_at_ms == clock.now
    assert new.portfolio.balances == {}  # fresh capital, nothing restored from the old run
    assert len(repo.runs["ab"]) == 2  # history of runs is kept


def test_definition_hash_covers_every_sizing_parameter() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    base = _trader(repo, "ab", AB, clock)
    assert base.definition() == _trader(repo, "ab", AB, clock).definition()
    config = base._config
    for changed in (
        replace(config, usdt_per_exchange=config.usdt_per_exchange + 1),
        replace(config, coin_per_route_usd=D(100)),
        replace(config, rebalance_threshold_pct=D(30)),
        replace(config, rebalance_delay_ms=1),
        replace(config, trade_notional_usd=D(500)),
        replace(config, transfer_tax_pct={"X": D(1)}),
        replace(config, coin_idle_release_ms=None),
        replace(config, conversion_cost_pct=D(1)),
    ):
        other = PaperTrader(changed, repo, base._estimator, clock, portfolio_id="ab", venues=AB)
        assert other.definition().config_hash != base.definition().config_hash


async def test_set_that_cannot_resume_is_dropped_and_the_others_keep_running() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    book = PaperBook(
        {"all": _trader(repo, "all", ALL, clock), "ab": _trader(repo, "ab", AB, clock)}
    )
    await book.start()
    ok_load = repo.load_state

    async def flaky(portfolio_id: str, since_ms: int = 0) -> None:
        if portfolio_id == "ab":
            raise ConnectionError("db down")
        return await ok_load(portfolio_id, since_ms)  # type: ignore[return-value]

    repo.load_state = flaky  # type: ignore[method-assign]
    await book.start()
    assert list(book.traders) == ["all"]  # `ab` is disabled, `all` is unaffected
    repo.load_state = ok_load  # type: ignore[method-assign]


async def test_book_start_fails_only_when_no_set_can_start() -> None:
    clock, repo = ManualClock(), MemoryPaper()

    async def broken(*args: object) -> None:
        raise ConnectionError("db down")

    repo.ensure_run = broken  # type: ignore[method-assign,assignment]
    book = PaperBook({"all": _trader(repo, "all", ALL, clock)})
    with pytest.raises(ConnectionError):
        await book.start()


# ------------------------------------------------------------------ coin slots (B)


async def test_idle_coin_slot_is_released_persisted_and_the_new_coin_trades() -> None:
    config = PaperConfig(
        usdt_per_exchange=D(5000),
        coin_per_route_usd=D(1000),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=30 * 60_000,
        coin_budget_per_venue_usd=D(1000),  # one coin slot per venue
        coin_idle_release_ms=24 * 3_600_000,
    )
    h = Harness(episodes=True, paper=True, paper_config=config)
    for ex, bid, ask in (("a", "99.9", "100"), ("b", "101", "101.1")):
        getattr(h, ex).quote("ABC/USDT", bid, ask)
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    assert [t.executed for t, _ in h.paper_repo.trades] == [True]
    # two days later a different coin needs the venue's only coin slot
    h.clock.now += 2 * 24 * 3_600_000
    for ex, bid, ask in (("a", "9.9", "10"), ("b", "10.1", "10.11")):
        getattr(h, ex).quote("DEF/USDT", bid, ask)
    h.a.quote("ABC/USDT", "50", "50.1")  # ABC spread is gone
    h.b.quote("ABC/USDT", "50", "50.1")
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    reasons = {t.symbol: t.skip_reason for t, _ in h.paper_repo.trades[1:]}
    assert reasons.get("DEF/USDT") is None, reasons  # traded thanks to the freed slot
    conversions = [r for r in h.paper_repo.rebalances.values() if r.network == "conversion"]
    assert [(c.asset, c.status) for c in conversions] == [("ABC", RebalanceStatus.COMPLETED)]
    assert conversions[0].fee_usd > 0
    book = h.scanner._paper
    assert book is not None
    portfolio = book.trader().portfolio
    assert ("b", "ABC") not in portfolio.seeds
    assert ("b", "DEF") in portfolio.seeds
    assert portfolio.rebalance_costs >= conversions[0].fee_usd


async def test_budget_exhausted_is_a_separate_skip_row_when_nothing_is_idle() -> None:
    config = PaperConfig(
        usdt_per_exchange=D(5000),
        coin_per_route_usd=D(1000),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=30 * 60_000,
        coin_budget_per_venue_usd=D(1000),
    )
    h = Harness(episodes=True, paper=True, paper_config=config)
    for symbol, ask, bid in (("ABC/USDT", "100", "101"), ("DEF/USDT", "10", "10.1")):
        h.a.quote(symbol, str(D(ask) - D("0.1")), ask)
        h.b.quote(symbol, bid, str(D(bid) + D("0.1")))
    await h.scanner.refresh_metadata()
    await h.scanner.sweep()
    await _settle(h)
    reasons = sorted(str(t.skip_reason) for t, _ in h.paper_repo.trades)
    assert reasons == ["None", str(SkipReason.COIN_BUDGET_EXHAUSTED)]


# ------------------------------------------------------------------ cap stats (C)


async def test_cap_binding_is_counted_per_set_and_persisted_hourly() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL, "ab": AB}, max_candidates=1)
    h.a.quote("ABC/USDT", "99.9", "100")
    h.b.quote("ABC/USDT", "101", "101.1")
    h.a.quote("DEF/USDT", "9.9", "10")
    h.c.quote("DEF/USDT", "10.6", "10.7")  # takes the only slot in `all`
    await h.scanner.refresh_metadata()
    result = await h.scanner.sweep()
    await _settle(h)
    assert result.candidates == 2
    assert result.candidates_cap == 1
    assert result.candidates_by_set == {"all": 1, "ab": 1}
    book = h.scanner._paper
    assert book is not None
    await book.flush_cap_stats(h.clock.now, force=True)
    stats = {d.portfolio_id: d for d in h.paper_repo.cap_stats}
    assert stats["all"].sweeps == 1
    assert stats["all"].sweeps_cap_bound == 1
    assert stats["all"].dropped_routes >= 1
    assert stats["ab"].sweeps_cap_bound == 0
    assert stats["ab"].dropped_routes == 0
    assert stats["all"].hour_ms == h.clock.now - h.clock.now % HOUR_MS
    # ABC alerted, was inside `all` (both legs) but outside its top-1: counted as excluded
    assert stats["all"].alerts_cap_excluded == 1
    assert stats["ab"].alerts_cap_excluded == 0


async def test_cap_stats_buffer_flushes_on_interval_and_survives_failures() -> None:
    repo = MemoryPaper()
    buf = CapStatsBuffer(repo, flush_interval_ms=1000)
    st = {"all": SetSweepStats(eligible=5, selected=3), "ab": SetSweepStats(2, 2)}
    t0 = 10 * HOUR_MS + 5
    buf.add_sweep(t0, st)
    buf.add_sweep(t0 + 10, st)
    await buf.flush(t0 + 10)  # first call only arms the interval
    assert repo.cap_stats == []
    repo.fail_cap_stats = True
    await buf.flush(t0 + 2000)  # fails: counters are kept
    repo.fail_cap_stats = False
    buf.add_sweep(t0 + 2500, st)
    buf.add_alert_excluded(t0 + 2500, ["all"])
    await buf.flush(t0 + 4000)
    by_pid = {d.portfolio_id: d for d in repo.cap_stats}
    assert by_pid["all"] == CapStatsDelta("all", 10 * HOUR_MS, 3, 3, 6, 1)
    assert by_pid["ab"] == CapStatsDelta("ab", 10 * HOUR_MS, 3, 0, 0, 0)
    repo.cap_stats.clear()
    await buf.flush(t0 + 10_000, force=True)
    assert repo.cap_stats == []  # nothing left to send


# ------------------------------------------------------------------ review points 5-7


async def test_missing_membership_fails_closed_with_per_set_caps() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL, "ab": AB})
    evaluation = SimpleNamespace(route_key="X|a>b", buy_exchange="a", sell_exchange="b")
    h.scanner._route_sets = {}
    assert h.scanner._membership(evaluation) == frozenset()  # type: ignore[arg-type]
    h.scanner._route_sets = {"X|a>b": frozenset({"ab"})}
    assert h.scanner._membership(evaluation) == frozenset({"ab"})  # type: ignore[arg-type]
    h.scanner._route_sets = None  # no per-set cap in force: unrestricted
    assert h.scanner._membership(evaluation) is None  # type: ignore[arg-type]


async def test_skip_rows_survive_missing_markets() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL, "ab": AB})
    book = h.scanner._paper
    assert book is not None
    outcomes = await book.execute(
        episode_id=None,
        symbol="ABC/USDT",
        base="ABC",
        buy_book=None,
        sell_book=None,
        buy_market=None,
        sell_market=None,
        transfer=UNKNOWN,
        network_quote=lambda *_: UNKNOWN,
        buy_exchange="a",
        sell_exchange="b",
    )
    assert {pid: o.skip_reason for pid, o in outcomes.items()} == {
        "all": SkipReason.BOOKS_UNAVAILABLE,
        "ab": SkipReason.BOOKS_UNAVAILABLE,
    }
    assert len(h.paper_repo.data["ab"].trades) == 1


class _Fatal(BaseException):
    """Not an Exception (like SystemExit / KeyboardInterrupt)."""


async def test_non_exception_errors_are_not_swallowed() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL, "ab": AB})
    book = h.scanner._paper
    assert book is not None

    async def fatal(*args: object, **kwargs: object) -> None:
        raise _Fatal

    book.trader("ab").execute = fatal  # type: ignore[method-assign,assignment]
    book.trader("ab").on_sweep = fatal  # type: ignore[method-assign]
    with pytest.raises(_Fatal):
        await book.execute(
            episode_id=None,
            symbol="ABC/USDT",
            base="ABC",
            buy_book=None,
            sell_book=None,
            buy_market=None,
            sell_market=None,
            transfer=UNKNOWN,
            network_quote=lambda *_: UNKNOWN,
            buy_exchange="a",
            sell_exchange="b",
        )
    with pytest.raises(_Fatal):
        await book.on_sweep(lambda *_: UNKNOWN)


async def test_cancellation_still_propagates() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL})
    book = h.scanner._paper
    assert book is not None

    async def cancelled(*args: object, **kwargs: object) -> None:
        raise asyncio.CancelledError

    book.trader("all").on_sweep = cancelled  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await book.on_sweep(lambda *_: UNKNOWN)


async def test_exceptions_are_isolated_and_logged_with_traceback() -> None:
    h = Harness(episodes=True, paper=True, paper_sets={"all": ALL, "ab": AB})
    book = h.scanner._paper
    assert book is not None

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("x")

    book.trader("ab").on_sweep = boom  # type: ignore[method-assign]
    await book.on_sweep(lambda *_: UNKNOWN)  # does not raise


def test_strategy_parameters_are_part_of_the_run_hash() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    base = _trader(repo, "ab", AB, clock)
    est = base._estimator.config
    cfg = base._config

    def other(
        estimator: EstimatorConfig | None = None, strategy: dict[str, str] | None = None
    ) -> PaperTrader:
        return PaperTrader(
            cfg,
            repo,
            NetSpreadEstimator(estimator or est, clock),
            clock,
            portfolio_id="ab",
            venues=AB,
            strategy=strategy,
        )

    reference = other(strategy={"latency_ms": "2000", "max_candidates_per_sweep": "30"})
    assert (
        reference.definition()
        == other(strategy={"max_candidates_per_sweep": "30", "latency_ms": "2000"}).definition()
    )
    changed = (
        other(replace(est, min_net_profit_pct=D("0.5")), reference._strategy),
        other(replace(est, min_net_profit_usd=D(9)), reference._strategy),
        other(replace(est, max_orderbook_age_ms=1000), reference._strategy),
        other(replace(est, max_gross_spread_pct=D(10)), reference._strategy),
        other(strategy={"latency_ms": "500", "max_candidates_per_sweep": "30"}),
        other(strategy={"latency_ms": "2000", "max_candidates_per_sweep": "60"}),
        other(strategy={"latency_ms": "2000"}),
    )
    for trader in changed:
        assert trader.definition().config_hash != reference.definition().config_hash


async def test_changed_strategy_starts_a_fresh_run_and_warns() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    first = _trader(repo, "ab", AB, clock)
    await first.start()
    assert first.run is not None
    assert first.run.created
    clock.now += 60_000
    changed = PaperTrader(
        first._config,
        repo,
        first._estimator,
        clock,
        portfolio_id="ab",
        venues=AB,
        strategy={"latency_ms": "100"},
    )
    with capture_logs() as logs:
        await changed.start()
    assert changed.run is not None
    assert changed.run.created
    assert changed.run.started_at_ms == clock.now
    [event] = [e for e in logs if e["event"] == "paper_run_restarted"]
    assert event["log_level"] == "warning"
    assert event["portfolio"] == "ab"
    assert event["since_ms"] == clock.now
    assert event["previous_hash"] == first.definition().config_hash[:12]
    assert event["config_hash"] == changed.definition().config_hash[:12]
    assert not any(e["event"] == "paper_run_started" for e in logs)


async def test_cap_stats_flush_times_out_without_losing_counters() -> None:
    repo = MemoryPaper()
    buf = CapStatsBuffer(repo, flush_interval_ms=1000, flush_timeout_s=0.05)
    buf.add_sweep(HOUR_MS, {"all": SetSweepStats(eligible=4, selected=2)})
    ok_add = repo.add_cap_stats

    async def hang(deltas: list[CapStatsDelta]) -> None:
        await asyncio.sleep(10)

    repo.add_cap_stats = hang  # type: ignore[method-assign,assignment]
    await buf.flush(HOUR_MS, force=True)  # returns after the timeout, does not raise
    assert repo.cap_stats == []
    repo.add_cap_stats = ok_add  # type: ignore[method-assign]
    await buf.flush(HOUR_MS + 10, force=True)
    assert [(d.portfolio_id, d.sweeps, d.dropped_routes) for d in repo.cap_stats] == [("all", 1, 2)]


async def test_cap_stats_flush_cancellation_keeps_counters() -> None:
    repo = MemoryPaper()
    buf = CapStatsBuffer(repo, flush_timeout_s=30)
    buf.add_sweep(HOUR_MS, {"all": SetSweepStats(eligible=1, selected=1)})
    ok_add = repo.add_cap_stats

    async def hang(deltas: list[CapStatsDelta]) -> None:
        await asyncio.sleep(10)

    repo.add_cap_stats = hang  # type: ignore[method-assign,assignment]
    task = asyncio.create_task(buf.flush(HOUR_MS, force=True))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    repo.add_cap_stats = ok_add  # type: ignore[method-assign]
    await buf.flush(HOUR_MS + 10, force=True)
    assert [d.sweeps for d in repo.cap_stats] == [1]


def test_capital_drift_above_configured_logs_a_warning_once() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    trader = _trader(repo, "ab", AB, clock)
    trader.portfolio.seeds[("a", "USDT")] = Seed(amount=D(99_999), price=D(1))
    with capture_logs() as logs:
        trader._check_capital()
        trader._check_capital()
    drift = [e for e in logs if e["event"] == "paper_capital_drift"]
    assert len(drift) == 1
    assert drift[0]["log_level"] == "warning"


def test_no_capital_warning_when_capital_is_at_or_below_configured() -> None:
    clock, repo = ManualClock(), MemoryPaper()
    trader = _trader(repo, "ab", AB, clock)
    with capture_logs() as logs:
        trader._check_capital()
    assert not [e for e in logs if e["event"] == "paper_capital_drift"]
