"""B15 part 2 (AC 5): the GO report repository returns the per-set manual sums."""

from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import PaperHolding, RunDefinition
from nexus.persistence.repositories import PaperRepository
from nexus.reports.go_repository import GoReportRepository, earliest_since_ms
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


async def test_load_sets_returns_manual_sums_per_set(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    for pid, offset, venues in (
        ("all", 0, ("binance", "bybit")),
        ("excl_conditional", H // 2, ("binance", "kucoin")),
    ):
        await repo.ensure_run(pid, RunDefinition(venues, D(10000), f"hash-{pid}"), T0 + offset)
    for pid, venues, n_trades, fee in (
        ("all", ("binance", "bybit"), 3, 2),
        ("excl_conditional", ("binance", "kucoin"), 1, 1),
    ):
        await repo.commit(
            portfolio_id=pid,
            at_ms=T0 + H,
            trades=[(_trade(venues[0], venues[1]), None)] * n_trades,
            rebalances=[_rebalance(venues[0], venues[1], fee)],
            holdings=[PaperHolding(v, "USDT", D(100), None, D(1)) for v in venues],
        )

    datas = await GoReportRepository(sessions).load_sets(T0 + 24 * H)

    by_name = {d.name: d for d in datas}
    assert set(by_name) == {"all", "excl_conditional"}
    assert next(d.name for d in datas) == "all"
    assert sum((t.net_usd for t in by_name["all"].trades), D(0)) == 3 * NET
    assert sum((t.net_usd for t in by_name["excl_conditional"].trades), D(0)) == NET
    assert sum((r.fee_usd for r in by_name["all"].rebalances), D(0)) == D(2)
    assert sum((r.fee_usd for r in by_name["excl_conditional"].rebalances), D(0)) == D(1)
    assert by_name["all"].run.started_ms == T0
    assert by_name["excl_conditional"].run.started_ms == T0 + H // 2
    assert earliest_since_ms(datas) == T0
    assert len(by_name["all"].snapshots) == 1
