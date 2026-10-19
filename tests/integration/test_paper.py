from dataclasses import replace
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.spread import TransferQuote, TransferStatus
from nexus.interfaces.repositories import PaperHolding
from nexus.persistence.repositories import PaperRepository
from nexus.simulation.portfolio import (
    PaperConfig,
    PaperPortfolio,
    RebalanceNeed,
    RebalanceStatus,
    SkipReason,
    TradeOutcome,
)
from tests.support import make_breakdown

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000


def _holdings(p: PaperPortfolio) -> list[PaperHolding]:
    return [
        PaperHolding(e, a, amount, p.seeds.get((e, a)), D(1) if a == "USDT" else p.prices.get(a))
        for (e, a), amount in sorted(p.balances.items())
    ]


async def test_commit_and_load_state(sessions: Sessions) -> None:
    repo = PaperRepository(sessions)
    assert await repo.load_state() is None
    p = PaperPortfolio(
        PaperConfig(D(1000), D(1000), D(20), 30 * 60_000, trade_notional_usd=D(1000))
    )
    p.mark_price("ABC", D(100))
    executed = p.trade("ABC/USDT", "ABC", "a", "b", make_breakdown(), T0)
    skipped = TradeOutcome("ABC/USDT", "ABC", "a", "b", T0, SkipReason.SPREAD_GONE)
    need = RebalanceNeed("USDT", "b", "a", D(500))
    rebalance = p.start_rebalance(need, TransferQuote(TransferStatus.VERIFIED, "TRC20", D(1)), T0)
    blocked = p.start_rebalance(
        RebalanceNeed("ABC", "a", "b", D(1)), TransferQuote(TransferStatus.UNKNOWN), T0
    )
    stored = await repo.commit(
        at_ms=T0,
        trades=[(executed, None), (skipped, None)],
        rebalances=[rebalance, blocked],
        holdings=_holdings(p),
    )
    assert all(r.id is not None for r in stored)
    state = await repo.load_state()
    assert state is not None
    assert state.realized == D("7.98101")
    assert state.rebalance_costs == D(1)  # blocked transfers cost nothing
    assert [r.id for r in state.in_flight] == [stored[0].id]
    assert {(h.exchange, h.asset): h.amount for h in state.holdings} == dict(p.balances)

    await repo.commit(
        at_ms=T0 + 1,
        trades=[],
        rebalances=[replace(stored[0], status=RebalanceStatus.COMPLETED)],
        holdings=_holdings(p),
    )
    state = await repo.load_state()
    assert state is not None
    assert state.in_flight == []
