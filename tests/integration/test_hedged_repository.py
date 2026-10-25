"""HT1 S10: hedged repository round trip on the test DB (CI only, never the live DB)."""

from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import (
    HedgedCoverageDelta,
    HedgedEvent,
    HedgedPoolState,
    HedgedSkip,
    RunDefinition,
)
from nexus.persistence.hedged_repository import HedgedPaperRepository
from nexus.simulation.hedged import evaluate_entry
from nexus.simulation.hedged_portfolio import HedgedPortfolio, HedgedPosition, PnlLines
from tests.unit.simulation.hedged_fixtures import config, request

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
HOUR = 3_600_000
VENUES = ["okx", "kucoin", "binance"]


def _definition(hash_: str = "h1") -> RunDefinition:
    return RunDefinition(tuple(VENUES), D(10000), hash_)


def _position() -> tuple[HedgedPortfolio, HedgedPosition]:
    cfg = config(p_stuck=0.0)
    req = request()
    port = HedgedPortfolio(cfg, VENUES, "h1")
    decision = evaluate_entry(cfg, req, port.entry_state())
    assert decision.plan is not None
    return port, port.open_position(decision.plan, req, "k1")


def _state(port: HedgedPortfolio) -> HedgedPoolState:
    return HedgedPoolState(dict(port.pools), list(port.rebalances), port.rebalance_fee_paid)


async def test_run_resume_and_new_run_on_changed_hash(sessions: Sessions) -> None:
    repo = HedgedPaperRepository(sessions)
    first = await repo.ensure_run("ht_a", _definition(), T0)
    assert first.created
    again = await repo.ensure_run("ht_a", _definition(), T0 + HOUR)
    assert not again.created
    assert again.run_id == first.run_id
    assert again.started_at_ms == T0
    changed = await repo.ensure_run("ht_a", _definition("h2"), T0 + 2 * HOUR)
    assert changed.created
    assert changed.run_id != first.run_id
    assert changed.previous_hash == "h1"


async def test_position_round_trip_and_idempotent_funding(sessions: Sessions) -> None:
    repo = HedgedPaperRepository(sessions)
    run = await repo.ensure_run("ht_a", _definition(), T0)
    port, pos = _position()
    pos.funding_times.add(T0)
    pos.lines = PnlLines(s=D("1.25"))
    funding = HedgedEvent(pos.key, "funding", T0, D("0.05"))
    skip = HedgedSkip(T0, "ABC", "okx", "kucoin", "SELL_THIN", "x")
    new = await repo.commit(
        run_id=run.run_id,
        at_ms=T0,
        positions=[pos],
        events=[funding],
        skips=[skip],
        state=_state(port),
    )
    assert new == 1
    dup = await repo.commit(
        run_id=run.run_id,
        at_ms=T0 + 1,
        positions=[pos],
        events=[funding],
        skips=[],
        state=_state(port),
    )
    assert dup == 0  # the unique key rejects the replayed funding time
    stored = await repo.load_state(run.run_id)
    assert stored.positions == [pos]
    assert stored.state == _state(port)


async def test_coverage_counters_are_additive(sessions: Sessions) -> None:
    repo = HedgedPaperRepository(sessions)
    run = await repo.ensure_run("ht_a", _definition(), T0)
    hour = T0 - T0 % HOUR
    await repo.add_coverage(
        run.run_id,
        [HedgedCoverageDelta(hour, "sweep", 20), HedgedCoverageDelta(hour, "perp:okx", 5)],
    )
    await repo.add_coverage(run.run_id, [HedgedCoverageDelta(hour, "sweep", 15)])
    got = await repo.load_coverage(run.run_id)
    assert {(c.source, c.minutes) for c in got} == {("sweep", 35), ("perp:okx", 5)}


async def test_deleting_a_run_cascades(sessions: Sessions) -> None:
    repo = HedgedPaperRepository(sessions)
    run = await repo.ensure_run("ht_a", _definition(), T0)
    await repo.add_coverage(run.run_id, [HedgedCoverageDelta(T0, "sweep", 1)])
    async with sessions.begin() as session:
        await session.execute(text("DELETE FROM paper_hedged_runs"))
        count = await session.scalar(text("SELECT count(*) FROM paper_hedged_coverage"))
    assert count == 0
