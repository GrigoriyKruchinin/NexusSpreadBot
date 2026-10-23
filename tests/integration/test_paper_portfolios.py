"""B15: per-set persistence and the per-set digest query return the manual sums."""

from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import PaperHolding
from nexus.persistence.repositories import DigestRepository, PaperRepository
from nexus.simulation.portfolio import Rebalance, RebalanceStatus, TradeOutcome
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


async def test_portfolios_are_isolated_and_summed_per_set(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
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
    assert by_id["all"].since_ms == T0 + H
