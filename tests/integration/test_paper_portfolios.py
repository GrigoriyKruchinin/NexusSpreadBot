"""B15: per-set persistence and the per-set digest query return the manual sums."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import CapStatsDelta, PaperHolding, RunDefinition
from nexus.persistence.repositories import DigestRepository, PaperRepository, RetentionRepository
from nexus.simulation.portfolio import Rebalance, RebalanceStatus, Seed, TradeOutcome
from tests.support import make_breakdown

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
H = 3_600_000
NET = D("7.98101")  # net profit of every trade built from make_breakdown()


def _trade(buy: str, sell: str) -> TradeOutcome:
    return TradeOutcome("ABC/USDT", "ABC", buy, sell, T0 + H, None, make_breakdown())


def _rebalance(src: str, dst: str, fee: int) -> Rebalance:
    return Rebalance(
        "USDT", src, dst, D(500), D(1), D(fee), "TRC20", T0 + H, T0 + 2 * H,
        RebalanceStatus.COMPLETED,
    )  # fmt: skip


async def _commit(
    repo: PaperRepository, pid: str, venues: list[str], n_trades: int, fee: int
) -> None:
    await repo.commit(
        portfolio_id=pid,
        at_ms=T0 + H,
        trades=[(_trade(venues[0], venues[1]), None)] * n_trades,
        rebalances=[_rebalance(venues[0], venues[1], fee)],
        holdings=[PaperHolding(v, "USDT", D(100), None, D(1)) for v in venues],
    )


def _definition(
    capital: str = "10000", venues: tuple[str, ...] = ("binance", "kucoin")
) -> RunDefinition:
    return RunDefinition(venues, D(capital), f"hash-{capital}-{'-'.join(venues)}")


async def test_portfolios_are_isolated_and_summed_per_set(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    await repo.ensure_run("all", _definition(), T0)
    await repo.ensure_run("excl_conditional", _definition(), T0 + H)
    await _commit(repo, "all", ["binance", "bybit"], 3, 2)
    await _commit(repo, "excl_conditional", ["binance", "kucoin"], 1, 1)

    all_state = await repo.load_state("all")
    excl_state = await repo.load_state("excl_conditional")
    assert await repo.load_state("excl_gateio") is None  # never backfilled
    assert all_state is not None
    assert excl_state is not None
    assert all_state.realized == 3 * NET
    assert all_state.rebalance_costs == D(2)
    assert {h.exchange for h in all_state.holdings} == {"binance", "bybit"}
    assert excl_state.realized == NET
    assert excl_state.rebalance_costs == D(1)
    assert {h.exchange for h in excl_state.holdings} == {"binance", "kucoin"}

    data = await DigestRepository(sessions).collect(T0, T0 + 3 * H)
    by_id = {p.portfolio_id: p for p in data.portfolios}
    assert list(by_id) == ["all", "excl_conditional"]  # 'all' first
    assert by_id["all"].trades == 3
    assert by_id["all"].hedged_pnl_usd == 3 * NET - 2
    assert by_id["excl_conditional"].trades == 1
    assert by_id["excl_conditional"].hedged_pnl_usd == NET - 1
    assert by_id["all"].since_ms == T0  # from the run registry, not from the first snapshot
    assert by_id["excl_conditional"].since_ms == T0 + H


async def test_run_registry_resumes_or_starts_a_new_run(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    first = await repo.ensure_run("core3", _definition(), T0)
    assert first.created
    assert first.started_at_ms == T0
    again = await repo.ensure_run("core3", _definition(), T0 + 5 * H)
    assert not again.created
    assert again.run_id == first.run_id
    assert again.started_at_ms == T0
    redefined = await repo.ensure_run("core3", _definition("5000"), T0 + 6 * H)
    assert redefined.created
    assert redefined.run_id > first.run_id
    assert redefined.started_at_ms == T0 + 6 * H
    # back to the first definition is yet another run (the latest run decides)
    third = await repo.ensure_run("core3", _definition(), T0 + 7 * H)
    assert third.created
    assert third.run_id > redefined.run_id


async def test_load_state_ignores_rows_of_earlier_runs(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    await _commit(repo, "all", ["binance", "bybit"], 3, 2)  # old run rows at T0 + H
    assert (await repo.load_state("all", T0 + 2 * H)) is None  # nothing in the new run yet
    await repo.commit(
        portfolio_id="all",
        at_ms=T0 + 3 * H,
        trades=[(_trade("binance", "kucoin"), None)],
        rebalances=[],
        holdings=[PaperHolding("binance", "USDT", D(7), None, D(1))],
    )
    state = await repo.load_state("all", T0 + 2 * H)
    assert state is not None
    assert [(h.exchange, h.amount) for h in state.holdings] == [("binance", D(7))]
    assert state.rebalance_costs == 0
    assert state.in_flight == []
    assert state.realized == 0  # the new trade is stamped T0 + H (before the new run)


async def test_since_survives_snapshot_retention(sessions: Sessions) -> None:
    now = datetime.now(tz=UTC)
    started_ms = int((now - timedelta(days=20)).timestamp() * 1000)
    repo = PaperRepository(sessions)
    await repo.ensure_run("all", _definition(), started_ms)
    for days_ago in (19, 12, 1):
        await repo.commit(
            portfolio_id="all",
            at_ms=int((now - timedelta(days=days_ago)).timestamp() * 1000),
            trades=[],
            rebalances=[],
            holdings=[PaperHolding("binance", "USDT", D(100), None, D(1))],
        )
    purged = await RetentionRepository(sessions).purge(
        snapshots_before=now - timedelta(days=7),
        evaluations_before=now - timedelta(days=30),
        episodes_before=now - timedelta(days=90),
    )
    assert purged["paper_balance_snapshots"] == 2  # the 19- and 12-day-old sets are gone
    data = await DigestRepository(sessions).collect(
        int((now - timedelta(days=1)).timestamp() * 1000), int(now.timestamp() * 1000)
    )
    [portfolio] = data.portfolios
    assert portfolio.since_ms == started_ms  # still the run start, not the retention horizon


async def test_cap_stats_are_added_per_set_and_hour(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    hour = T0 - T0 % H
    await repo.add_cap_stats([CapStatsDelta("all", hour, 10, 4, 12, 1)])
    await repo.add_cap_stats(
        [CapStatsDelta("all", hour, 5, 1, 3, 0), CapStatsDelta("ab", hour, 5, 0, 0, 2)]
    )
    await repo.add_cap_stats([])
    async with sessions() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT portfolio_id, sweeps, sweeps_cap_bound, dropped_routes, "
                    "alerts_cap_excluded FROM paper_cap_stats ORDER BY portfolio_id"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [("ab", 5, 0, 0, 2), ("all", 15, 5, 15, 1)]


async def test_digest_paper_block_ignores_rows_of_earlier_runs(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    old_flight = Rebalance(
        "USDT", "binance", "bybit", D(900), D(1), D(50), "TRC20", T0 + H, T0 + 9 * H,
        RebalanceStatus.IN_FLIGHT,
    )  # fmt: skip
    await repo.commit(  # an earlier definition of "all", never restored by the new run
        portfolio_id="all",
        at_ms=T0 + H,
        trades=[(_trade("binance", "bybit"), None)] * 4,
        rebalances=[_rebalance("binance", "bybit", 40), old_flight],
        holdings=[PaperHolding("binance", "USDT", D(5000), Seed(D(5000), D(1)), D(1))],
    )
    await repo.ensure_run("all", _definition(), T0 + 2 * H)
    await repo.commit(
        portfolio_id="all",
        at_ms=T0 + 3 * H,
        trades=[(_trade("binance", "kucoin"), None)],
        rebalances=[_rebalance("binance", "kucoin", 3)],
        holdings=[PaperHolding("binance", "USDT", D(100), Seed(D(100), D(1)), D(1))],
    )
    data = await DigestRepository(sessions).collect(T0, T0 + 5 * H)
    paper = data.paper
    assert paper is not None
    assert paper.trades == 1
    assert paper.realized_total_usd == NET
    assert paper.realized_total_excl_conditional_usd == NET
    assert paper.rebalance_total_usd == D(3)
    assert paper.rebalance_total_excl_conditional_usd == D(3)
    assert paper.rebalances == 1
    assert paper.capital_usd == D(100)
    assert paper.equity_usd == D(100)  # the old IN_FLIGHT 900 USDT is not added


async def test_digest_flags_a_set_restarted_inside_the_window(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    await repo.ensure_run("all", _definition(), T0)
    await repo.ensure_run("all", _definition("5000"), T0 + 2 * H)  # definition changed
    await repo.ensure_run("kept", _definition(), T0)
    digest = DigestRepository(sessions)
    inside = await digest.collect(T0 + H, T0 + 5 * H)
    assert {p.portfolio_id: p.restarted for p in inside.portfolios} == {"all": True, "kept": False}
    assert {p.portfolio_id: p.since_ms for p in inside.portfolios}["all"] == T0 + 2 * H
    later = await digest.collect(T0 + 3 * H, T0 + 5 * H)  # restart is older than the window
    assert not any(p.restarted for p in later.portfolios)
