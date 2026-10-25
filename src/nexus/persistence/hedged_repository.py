"""PostgreSQL repository of the hedged-transfer paper strategy (``paper_hedged_*`` tables only)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import (
    HedgedCoverageDelta,
    HedgedEvent,
    HedgedPoolState,
    HedgedSkip,
    HedgedStored,
    IHedgedPaperRepository,
    PortfolioRun,
    RunDefinition,
)
from nexus.persistence.models import (
    PaperHedgedCoverageRow,
    PaperHedgedEventRow,
    PaperHedgedPositionRow,
    PaperHedgedRunRow,
    PaperHedgedSkipRow,
    PaperHedgedStateRow,
)
from nexus.persistence.repositories import datetime_to_ms, ms_to_datetime
from nexus.simulation.hedged import EntryPlan
from nexus.simulation.hedged_portfolio import (
    HedgedPosition,
    HedgedStatus,
    PnlLines,
    Rebalance,
)

Sessions = async_sessionmaker[AsyncSession]
_DEC = "$d"
_SET = "$s"


def encode(value: object) -> object:
    """JSON-safe form: Decimals and sets are tagged so they round-trip exactly."""
    if isinstance(value, Decimal):
        return {_DEC: str(value)}
    if isinstance(value, (set, frozenset)):
        return {_SET: sorted(value)}
    if isinstance(value, Mapping):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, HedgedStatus):
        return value.value
    return value


def decode(value: object) -> object:
    """Inverse of :func:`encode`."""
    if isinstance(value, dict):
        if set(value) == {_DEC}:
            return Decimal(value[_DEC])
        if set(value) == {_SET}:
            return set(value[_SET])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def position_to_payload(pos: HedgedPosition) -> dict[str, object]:
    """Full position state as JSON (``asdict`` recurses into the plan and the P&L lines)."""
    return cast("dict[str, object]", encode(asdict(pos)))


def payload_to_position(payload: Mapping[str, object]) -> HedgedPosition:
    """Rebuild a position stored by :func:`position_to_payload`."""
    data = cast("dict[str, Any]", decode(dict(payload)))
    data["plan"] = EntryPlan(**data["plan"])
    if data.get("lines") is not None:
        data["lines"] = PnlLines(**data["lines"])
    data["status"] = HedgedStatus(data["status"])
    return HedgedPosition(**data)


def state_to_payload(state: HedgedPoolState) -> dict[str, object]:
    """Pools and in-flight rebalances as JSON."""
    return cast(
        "dict[str, object]",
        encode(
            {
                "pools": state.pools,
                "rebalances": [asdict(r) for r in state.rebalances],
                "rebalance_fee_paid": state.rebalance_fee_paid,
            }
        ),
    )


def payload_to_state(payload: Mapping[str, object]) -> HedgedPoolState:
    """Inverse of :func:`state_to_payload`."""
    data = cast("dict[str, Any]", decode(dict(payload)))
    return HedgedPoolState(
        pools=data["pools"],
        rebalances=[Rebalance(**r) for r in data["rebalances"]],
        rebalance_fee_paid=data["rebalance_fee_paid"],
    )


class HedgedPaperRepository(IHedgedPaperRepository):
    """Runs, positions, idempotent events, skips, pool state and coverage counters."""

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def ensure_run(self, set_id: str, definition: RunDefinition, now_ms: int) -> PortfolioRun:
        """Resume the latest run of the set when its hash matches, else start a new run."""
        async with self._sessions.begin() as session:
            latest = await session.scalar(
                select(PaperHedgedRunRow)
                .where(PaperHedgedRunRow.set_id == set_id)
                .order_by(PaperHedgedRunRow.id.desc())
                .limit(1)
            )
            if latest is not None and latest.config_hash == definition.config_hash:
                return PortfolioRun(
                    set_id, latest.id, datetime_to_ms(latest.started_at), definition
                )
            row = PaperHedgedRunRow(
                set_id=set_id,
                started_at=ms_to_datetime(now_ms),
                venues=",".join(definition.venues),
                capital_usd=definition.capital_usd,
                config_hash=definition.config_hash,
            )
            session.add(row)
            await session.flush()
            return PortfolioRun(
                set_id,
                row.id,
                now_ms,
                definition,
                created=True,
                previous_hash=latest.config_hash if latest is not None else None,
            )

    async def commit(
        self,
        *,
        run_id: int,
        at_ms: int,
        positions: Sequence[HedgedPosition],
        events: Sequence[HedgedEvent],
        skips: Sequence[HedgedSkip],
        state: HedgedPoolState,
    ) -> int:
        """Atomic write of one engine step; duplicate events are ignored by their unique key."""
        new_events = 0
        async with self._sessions.begin() as session:
            for pos in positions:
                values = _position_values(run_id, pos)
                update = {k: v for k, v in values.items() if k not in ("run_id", "position_key")}
                await session.execute(
                    pg_insert(PaperHedgedPositionRow)
                    .values(values)
                    .on_conflict_do_update(
                        constraint="uq_paper_hedged_positions_run_key", set_=update
                    )
                )
            for event in events:
                result = await session.execute(
                    pg_insert(PaperHedgedEventRow)
                    .values(
                        run_id=run_id,
                        position_key=event.position_key,
                        kind=event.kind,
                        event_ms=event.event_ms,
                        amount=event.amount,
                        detail=event.detail,
                    )
                    .on_conflict_do_nothing(constraint="uq_paper_hedged_events_key")
                    .returning(PaperHedgedEventRow.id)
                )
                if result.scalar_one_or_none() is not None:
                    new_events += 1
            session.add_all(
                PaperHedgedSkipRow(
                    run_id=run_id,
                    at=ms_to_datetime(s.at_ms),
                    coin=s.coin,
                    buy_venue=s.buy_venue,
                    sell_venue=s.sell_venue,
                    reason=s.reason,
                    detail=s.detail,
                )
                for s in skips
            )
            payload = state_to_payload(state)
            updated = ms_to_datetime(at_ms)
            await session.execute(
                pg_insert(PaperHedgedStateRow)
                .values(run_id=run_id, updated_at=updated, payload=payload)
                .on_conflict_do_update(
                    index_elements=["run_id"], set_={"updated_at": updated, "payload": payload}
                )
            )
        return new_events

    async def load_state(self, run_id: int) -> HedgedStored:
        """Pool state and every position of the run."""
        async with self._sessions() as session:
            state_row = await session.scalar(
                select(PaperHedgedStateRow).where(PaperHedgedStateRow.run_id == run_id)
            )
            rows = (
                await session.scalars(
                    select(PaperHedgedPositionRow)
                    .where(PaperHedgedPositionRow.run_id == run_id)
                    .order_by(PaperHedgedPositionRow.id)
                )
            ).all()
        return HedgedStored(
            state=payload_to_state(state_row.payload) if state_row is not None else None,
            positions=[payload_to_position(r.payload) for r in rows],
        )

    async def add_coverage(self, run_id: int, deltas: Sequence[HedgedCoverageDelta]) -> None:
        """Additive upsert of the hourly counters."""
        if not deltas:
            return
        async with self._sessions.begin() as session:
            for d in deltas:
                stmt = pg_insert(PaperHedgedCoverageRow).values(
                    run_id=run_id,
                    hour_start=ms_to_datetime(d.hour_ms),
                    source=d.source,
                    minutes=d.minutes,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["run_id", "hour_start", "source"],
                        set_={"minutes": PaperHedgedCoverageRow.minutes + stmt.excluded.minutes},
                    )
                )

    async def load_coverage(self, run_id: int) -> list[HedgedCoverageDelta]:
        """All counters of the run, oldest hour first."""
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(PaperHedgedCoverageRow)
                    .where(PaperHedgedCoverageRow.run_id == run_id)
                    .order_by(PaperHedgedCoverageRow.hour_start, PaperHedgedCoverageRow.source)
                )
            ).all()
        return [
            HedgedCoverageDelta(datetime_to_ms(r.hour_start), r.source, r.minutes) for r in rows
        ]


def _position_values(run_id: int, pos: HedgedPosition) -> dict[str, Any]:
    closed: datetime | None = ms_to_datetime(pos.closed_ms) if pos.closed_ms is not None else None
    return {
        "run_id": run_id,
        "position_key": pos.key,
        "coin": pos.coin,
        "buy_venue": pos.buy_venue,
        "sell_venue": pos.sell_venue,
        "hedge_venue": pos.plan.hedge_venue,
        "status": pos.status.value,
        "opened_at": ms_to_datetime(pos.opened_ms),
        "closed_at": closed,
        "pnl_total": pos.lines.total if pos.lines is not None else None,
        "hedge_break": pos.hedge_break,
        "hedge_unpriced": pos.hedge_unpriced or pos.hedge_unpriced_final,
        "payload": position_to_payload(pos),
    }
