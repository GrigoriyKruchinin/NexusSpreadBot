"""Read-only query layer of the GO report (SELECTs only; use the ``nexus_ro`` role).

Builds the plain :class:`~nexus.reports.go_math.SetData` rows the pure math consumes. Nothing is
written; no query touches a table outside the paper/registry/evaluation read paths.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.spread import EvaluationStatus
from nexus.persistence.models import (
    PaperBalanceSnapshotRow,
    PaperCapStatsRow,
    PaperPortfolioRow,
    PaperRebalanceRow,
    PaperTradeRow,
    SpreadEvaluationRow,
)
from nexus.persistence.repositories import datetime_to_ms, ms_to_datetime
from nexus.reports.go_build import FeeObservation
from nexus.reports.go_math import (
    HOUR_MS,
    ZERO,
    CapHour,
    HoldingPoint,
    RebalanceRecord,
    RunInfo,
    SetData,
    SkipRecord,
    SnapshotSet,
    TradeRecord,
)

Sessions = async_sessionmaker[AsyncSession]


def _run_info(row: PaperPortfolioRow) -> RunInfo:
    return RunInfo(
        run_id=row.id,
        started_ms=datetime_to_ms(row.started_at),
        venues=tuple(v for v in row.venues.split(",") if v),
        capital_usd=row.capital_usd,
        config_hash=row.config_hash,
    )


def pick_hourly(times_ms: list[int]) -> list[int]:
    """Keep the last instant of every UTC hour (bounds the snapshot rows read)."""
    last: dict[int, int] = {}
    for t in sorted(times_ms):
        last[t // HOUR_MS] = t
    return sorted(last.values())


class GoReportRepository:
    """Per-set report inputs and fee observations."""

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def load_sets(self, until_ms: int) -> list[SetData]:
        """The latest run of every set started before ``until_ms`` with its rows in the run."""
        until = ms_to_datetime(until_ms)
        async with self._sessions() as session:
            runs: dict[str, list[PaperPortfolioRow]] = defaultdict(list)
            for row in (
                await session.scalars(
                    select(PaperPortfolioRow)
                    .where(PaperPortfolioRow.started_at < until)
                    .order_by(PaperPortfolioRow.id)
                )
            ).all():
                runs[row.portfolio_id].append(row)
            result = []
            for name in sorted(runs, key=lambda n: (n != "all", n)):
                *earlier, latest = runs[name]
                result.append(
                    await self._load_set(
                        session, name, _run_info(latest), [_run_info(r) for r in earlier], until
                    )
                )
        return result

    async def _load_set(
        self,
        session: AsyncSession,
        name: str,
        run: RunInfo,
        earlier: list[RunInfo],
        until: datetime,
    ) -> SetData:
        since = ms_to_datetime(run.started_ms)
        trade, rebal, caps = PaperTradeRow, PaperRebalanceRow, PaperCapStatsRow
        in_run_trades = (
            trade.portfolio_id == name,
            trade.executed_at >= since,
            trade.executed_at < until,
        )
        trades = [
            TradeRecord(
                at_ms=datetime_to_ms(r.executed_at),
                symbol=r.symbol,
                base=r.base,
                buy_exchange=r.buy_exchange,
                sell_exchange=r.sell_exchange,
                net_usd=r.net_usd or ZERO,
                notional_usd=r.cost_quote or ZERO,
            )
            for r in (
                await session.scalars(select(trade).where(*in_run_trades, trade.executed.is_(True)))
            ).all()
        ]
        skips = [
            SkipRecord(datetime_to_ms(at), reason or "unknown")
            for at, reason in (
                await session.execute(
                    select(trade.executed_at, trade.skip_reason).where(
                        *in_run_trades, trade.executed.is_(False)
                    )
                )
            ).all()
        ]
        rebalances = [
            RebalanceRecord(
                started_ms=datetime_to_ms(r.started_at),
                arrives_ms=datetime_to_ms(r.arrives_at),
                asset=r.asset,
                from_exchange=r.from_exchange,
                to_exchange=r.to_exchange,
                amount=r.amount,
                fee=r.fee,
                fee_usd=r.fee_usd,
                network=r.network,
                status=r.status,
            )
            for r in (
                await session.scalars(
                    select(rebal).where(
                        rebal.portfolio_id == name,
                        rebal.started_at >= since,
                        rebal.started_at < until,
                    )
                )
            ).all()
        ]
        cap_hours = [
            CapHour(
                hour_ms=datetime_to_ms(r.hour),
                sweeps=r.sweeps,
                sweeps_cap_bound=r.sweeps_cap_bound,
                dropped_routes=r.dropped_routes,
                alerts_cap_excluded=r.alerts_cap_excluded,
            )
            for r in (
                await session.scalars(
                    select(caps).where(
                        caps.portfolio_id == name,
                        caps.hour >= ms_to_datetime(run.started_ms - run.started_ms % HOUR_MS),
                        caps.hour < until,
                    )
                )
            ).all()
        ]
        snapshots = await self._snapshots(session, name, since, until)
        return SetData(
            name=name,
            run=run,
            previous_runs=tuple(earlier),
            snapshots=tuple(snapshots),
            trades=tuple(sorted(trades, key=lambda t: t.at_ms)),
            skips=tuple(sorted(skips, key=lambda s: s.at_ms)),
            rebalances=tuple(sorted(rebalances, key=lambda r: r.started_ms)),
            caps=tuple(sorted(cap_hours, key=lambda c: c.hour_ms)),
        )

    @staticmethod
    async def _snapshots(
        session: AsyncSession, name: str, since: datetime, until: datetime
    ) -> list[SnapshotSet]:
        """Hourly-thinned snapshot sets of the run (the last set of each UTC hour)."""
        snap = PaperBalanceSnapshotRow
        stamps = (
            await session.scalars(
                select(snap.captured_at)
                .where(
                    snap.portfolio_id == name, snap.captured_at >= since, snap.captured_at < until
                )
                .distinct()
            )
        ).all()
        by_ms = {datetime_to_ms(s): s for s in stamps}
        keep = [by_ms[t] for t in pick_hourly(list(by_ms))]
        if not keep:
            return []
        grouped: dict[int, list[HoldingPoint]] = defaultdict(list)
        for r in (
            await session.scalars(
                select(snap).where(snap.portfolio_id == name, snap.captured_at.in_(keep))
            )
        ).all():
            seeded = (
                r.seed_amount * r.seed_price
                if r.seed_amount is not None and r.seed_price is not None
                else ZERO
            )
            price = r.price_usd if r.price_usd is not None else r.seed_price
            grouped[datetime_to_ms(r.captured_at)].append(
                HoldingPoint(r.exchange, r.asset, r.amount, price, seeded)
            )
        return [SnapshotSet(at, tuple(h)) for at, h in sorted(grouped.items())]

    async def fee_observations(self, since_ms: int, until_ms: int) -> list[FeeObservation]:
        """Effective fee % per venue on profitable evaluations (F2: what fees were applied)."""
        ev = SpreadEvaluationRow
        window = (
            ev.evaluated_at >= ms_to_datetime(since_ms),
            ev.evaluated_at < ms_to_datetime(until_ms),
            ev.status == EvaluationStatus.PROFITABLE.value,
        )
        buy_pct = ev.fee_buy_usd / ev.cost_quote * 100
        sell_pct = ev.fee_sell_usd / ev.proceeds_quote * 100
        merged: dict[str, list[tuple[int, Decimal, Decimal, Decimal]]] = defaultdict(list)
        async with self._sessions() as session:
            for venue_col, pct, filled in (
                (ev.buy_exchange, buy_pct, (ev.fee_buy_usd.is_not(None), ev.cost_quote > 0)),
                (ev.sell_exchange, sell_pct, (ev.fee_sell_usd.is_not(None), ev.proceeds_quote > 0)),
            ):
                rows = await session.execute(
                    select(venue_col, func.count(), func.avg(pct), func.min(pct), func.max(pct))
                    .where(*window, *filled)
                    .group_by(venue_col)
                )
                for venue, n, avg, low, high in rows.all():
                    merged[venue].append((int(n), Decimal(avg), Decimal(low), Decimal(high)))
        result = []
        for venue in sorted(merged):
            parts = merged[venue]
            n = sum(p[0] for p in parts)
            result.append(
                FeeObservation(
                    venue=venue,
                    samples=n,
                    avg_pct=sum((p[1] * p[0] for p in parts), ZERO) / n,
                    min_pct=min(p[2] for p in parts),
                    max_pct=max(p[3] for p in parts),
                )
            )
        return result


def earliest_since_ms(datas: list[SetData]) -> int | None:
    """Earliest run start among the sets (lower bound of the fee observation window)."""
    return min((d.run.started_ms for d in datas), default=None)
