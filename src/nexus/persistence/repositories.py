"""PostgreSQL repository implementations."""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from nexus.domain.conditional import touches_conditional
from nexus.domain.digest import (
    HOUR_MS,
    DigestData,
    EpisodeStats,
    EpisodeSummary,
    PaperStats,
    PortfolioSummary,
    QuarantineSummary,
    SetCoverage,
    compute_set_coverage,
)
from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.models import MarketInfo
from nexus.domain.quarantine import RouteQuarantine
from nexus.domain.spread import (
    EvaluationStatus,
    SpreadBreakdown,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)
from nexus.engine.candidates import RouteQuote
from nexus.interfaces.repositories import (
    AlertDeliveryStatus,
    CapStatsDelta,
    ExchangeMetadataStats,
    IAlertLogRepository,
    IDigestRepository,
    IEpisodeRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    IMetadataStatsRepository,
    IPaperRepository,
    IQuarantineRepository,
    IRetentionRepository,
    ISnapshotRepository,
    PaperHolding,
    PaperState,
    PortfolioRun,
    RunDefinition,
)
from nexus.interfaces.watchdog import IPaperSetActivity, IScannerActivity, PaperSetActivity
from nexus.persistence.models import (
    AlertLogRow,
    ExchangeHealthRow,
    ExchangeMetadataStatsRow,
    MarketPairRow,
    OpportunityEpisodeRow,
    PaperBalanceSnapshotRow,
    PaperCapStatsRow,
    PaperPortfolioRow,
    PaperRebalanceRow,
    PaperTradeRow,
    RouteQuarantineRow,
    SpreadEvaluationRow,
    SpreadSnapshotRow,
)
from nexus.simulation.portfolio import (
    DEFAULT_PORTFOLIO_ID,
    Rebalance,
    RebalanceStatus,
    Seed,
    TradeOutcome,
)

Sessions = async_sessionmaker[AsyncSession]

_BREAKDOWN_FIELDS: tuple[str, ...] = tuple(
    name for name in SpreadBreakdown.__dataclass_fields__ if name != "gross_spread_pct"
)


def ms_to_datetime(epoch_ms: int) -> datetime:
    """Epoch milliseconds to an aware UTC datetime."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def datetime_to_ms(value: datetime) -> int:
    """Aware datetime to epoch milliseconds."""
    return int(value.timestamp() * 1000)


def evaluation_to_row(evaluation: SpreadEvaluation) -> SpreadEvaluationRow:
    """Map a domain evaluation onto an ORM row."""
    values: dict[str, Any] = {
        "evaluated_at": ms_to_datetime(evaluation.evaluated_at_ms),
        "symbol": evaluation.symbol,
        "base": evaluation.base,
        "quote": evaluation.quote,
        "buy_exchange": evaluation.buy_exchange,
        "sell_exchange": evaluation.sell_exchange,
        "status": evaluation.status.value,
        "reason": evaluation.reason,
        "fees_estimated": evaluation.fees_estimated,
        "notional_usd": evaluation.notional_usd,
        "gross_spread_pct": evaluation.gross_spread_pct,
        "buy_book_age_ms": evaluation.buy_book_age_ms,
        "sell_book_age_ms": evaluation.sell_book_age_ms,
        "transfer_status": evaluation.transfer.status.value,
        "transfer_network": evaluation.transfer.network,
        "transfer_fee_base": evaluation.transfer.fee_base,
        "transfer_note": evaluation.transfer.note,
    }
    breakdown = evaluation.breakdown
    for name in _BREAKDOWN_FIELDS:
        values[name] = getattr(breakdown, name) if breakdown is not None else None
    return SpreadEvaluationRow(**values)


def row_to_evaluation(row: SpreadEvaluationRow) -> SpreadEvaluation:
    """Map an ORM row back onto a domain evaluation."""
    breakdown: SpreadBreakdown | None = None
    values = {name: getattr(row, name) for name in _BREAKDOWN_FIELDS}
    if all(value is not None for value in values.values()) and row.gross_spread_pct is not None:
        breakdown = SpreadBreakdown(gross_spread_pct=row.gross_spread_pct, **values)
    return SpreadEvaluation(
        symbol=row.symbol,
        base=row.base,
        quote=row.quote,
        buy_exchange=row.buy_exchange,
        sell_exchange=row.sell_exchange,
        notional_usd=row.notional_usd,
        status=EvaluationStatus(row.status),
        transfer=TransferQuote(
            status=TransferStatus(row.transfer_status),
            network=row.transfer_network,
            fee_base=row.transfer_fee_base,
            note=row.transfer_note or "",
        ),
        buy_book_age_ms=row.buy_book_age_ms,
        sell_book_age_ms=row.sell_book_age_ms,
        evaluated_at_ms=datetime_to_ms(row.evaluated_at),
        gross_spread_pct=row.gross_spread_pct,
        breakdown=breakdown,
        reason=row.reason or "",
        fees_estimated=bool(row.fees_estimated),
    )


class _Repository:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions


class MarketRepository(_Repository, IMarketRepository):
    """Upserts market metadata keyed by (exchange, symbol)."""

    _BATCH = 1_000

    async def upsert_markets(self, markets: Sequence[MarketInfo]) -> int:
        """Insert or update markets; returns the number of rows written."""
        if not markets:
            return 0
        async with self._sessions.begin() as session:
            for start in range(0, len(markets), self._BATCH):
                rows = [
                    {
                        "exchange": m.exchange,
                        "symbol": m.symbol,
                        "base": m.base,
                        "quote": m.quote,
                        "taker_fee": m.taker_fee,
                        "taker_fee_is_default": m.taker_fee_is_default,
                        "amount_step": m.amount_step,
                        "min_amount": m.min_amount,
                        "min_cost": m.min_cost,
                        "active": m.active,
                    }
                    for m in markets[start : start + self._BATCH]
                ]
                stmt = pg_insert(MarketPairRow).values(rows)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_market_pairs_exchange_symbol",
                    set_={
                        col: stmt.excluded[col]
                        for col in rows[0]
                        if col not in {"exchange", "symbol"}
                    }
                    | {"updated_at": datetime.now(tz=UTC)},
                )
                await session.execute(stmt)
        return len(markets)


class SnapshotRepository(_Repository, ISnapshotRepository):
    """Stores top-of-book route quotes."""

    async def add_snapshots(self, captured_at: datetime, routes: Sequence[RouteQuote]) -> int:
        """Store route quotes captured at ``captured_at``."""
        if not routes:
            return 0
        async with self._sessions.begin() as session:
            session.add_all(
                SpreadSnapshotRow(
                    captured_at=captured_at,
                    symbol=r.symbol,
                    buy_exchange=r.buy_exchange,
                    sell_exchange=r.sell_exchange,
                    ask=r.ask,
                    bid=r.bid,
                    gross_spread_pct=r.gross_spread_pct,
                    fee_bound_net_pct=r.fee_bound_net_pct,
                )
                for r in routes
            )
        return len(routes)


class EvaluationRepository(_Repository, IEvaluationRepository):
    """Stores and loads spread evaluations."""

    async def add_evaluations(
        self,
        evaluations: Sequence[SpreadEvaluation],
        episode_ids: Sequence[int | None] | None = None,
    ) -> list[int]:
        """Store evaluations (optionally linked to episodes); returns ids in input order."""
        if not evaluations:
            return []
        links = list(episode_ids) if episode_ids is not None else [None] * len(evaluations)
        if len(links) != len(evaluations):
            msg = "episode_ids must align with evaluations"
            raise ValueError(msg)
        rows = [evaluation_to_row(e) for e in evaluations]
        for row, episode_id in zip(rows, links, strict=True):
            row.episode_id = episode_id
        async with self._sessions.begin() as session:
            session.add_all(rows)
            await session.flush()
            return [row.id for row in rows]

    async def get(self, evaluation_id: int) -> SpreadEvaluation | None:
        """Load one evaluation by id."""
        async with self._sessions() as session:
            row = await session.get(SpreadEvaluationRow, evaluation_id)
            return row_to_evaluation(row) if row is not None else None


def _optional_dt(epoch_ms: int | None) -> datetime | None:
    return ms_to_datetime(epoch_ms) if epoch_ms is not None else None


def _optional_ms(value: datetime | None) -> int | None:
    return datetime_to_ms(value) if value is not None else None


def _episode_state(episode: OpportunityEpisode) -> dict[str, Any]:
    """Columns that change over an episode's life."""
    return {
        "last_seen_at": ms_to_datetime(episode.last_seen_at_ms),
        "closed_at": _optional_dt(episode.closed_at_ms),
        "close_reason": episode.close_reason.value if episode.close_reason else None,
        "peak_net_usd": episode.peak_net_usd,
        "last_net_usd": episode.last_net_usd,
        "peak_net_pct": episode.peak_net_pct,
        "evaluations": episode.evaluations,
        "transfer_status": episode.transfer_status.value,
        "transfer_network": episode.transfer_network,
        "alerted_at": _optional_dt(episode.alerted_at_ms),
        "alerted_net_usd": episode.alerted_net_usd,
        "realerts": episode.realerts,
        "survived_latency": episode.survived_latency,
        "unverified_since": _optional_dt(episode.unverified_since_ms),
    }


def episode_to_row(episode: OpportunityEpisode) -> OpportunityEpisodeRow:
    """Map a domain episode onto an ORM row."""
    return OpportunityEpisodeRow(
        symbol=episode.symbol,
        buy_exchange=episode.buy_exchange,
        sell_exchange=episode.sell_exchange,
        opened_at=ms_to_datetime(episode.opened_at_ms),
        first_net_usd=episode.first_net_usd,
        **_episode_state(episode),
    )


def row_to_episode(row: OpportunityEpisodeRow) -> OpportunityEpisode:
    """Map an ORM row back onto a domain episode."""
    return OpportunityEpisode(
        id=row.id,
        symbol=row.symbol,
        buy_exchange=row.buy_exchange,
        sell_exchange=row.sell_exchange,
        opened_at_ms=datetime_to_ms(row.opened_at),
        last_seen_at_ms=datetime_to_ms(row.last_seen_at),
        closed_at_ms=_optional_ms(row.closed_at),
        close_reason=EpisodeCloseReason(row.close_reason) if row.close_reason else None,
        first_net_usd=row.first_net_usd,
        peak_net_usd=row.peak_net_usd,
        last_net_usd=row.last_net_usd,
        peak_net_pct=row.peak_net_pct,
        evaluations=row.evaluations,
        transfer_status=TransferStatus(row.transfer_status),
        transfer_network=row.transfer_network,
        alerted_at_ms=_optional_ms(row.alerted_at),
        alerted_net_usd=row.alerted_net_usd,
        realerts=row.realerts,
        survived_latency=row.survived_latency,
        unverified_since_ms=_optional_ms(row.unverified_since),
    )


class EpisodeRepository(_Repository, IEpisodeRepository):
    """Stores opportunity episodes."""

    async def open(self, episode: OpportunityEpisode) -> OpportunityEpisode:
        """Insert a new open episode, or return the route's already open one (see interface)."""
        if not episode.is_open:
            msg = "only open episodes can be inserted"
            raise ValueError(msg)
        row = episode_to_row(episode)
        values = {c.key: getattr(row, c.key) for c in OpportunityEpisodeRow.__table__.columns}
        values.pop("id")
        insert = (
            pg_insert(OpportunityEpisodeRow)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["symbol", "buy_exchange", "sell_exchange"],
                index_where=OpportunityEpisodeRow.closed_at.is_(None),
            )
            .returning(OpportunityEpisodeRow.id)
        )
        async with self._sessions.begin() as session:
            new_id = await session.scalar(insert)
            if new_id is not None:
                return replace(episode, id=new_id)
            existing = await session.scalar(
                select(OpportunityEpisodeRow).where(
                    OpportunityEpisodeRow.symbol == episode.symbol,
                    OpportunityEpisodeRow.buy_exchange == episode.buy_exchange,
                    OpportunityEpisodeRow.sell_exchange == episode.sell_exchange,
                    OpportunityEpisodeRow.closed_at.is_(None),
                )
            )
            if existing is None:  # pragma: no cover - closed concurrently; never in practice
                msg = f"open episode of {episode.route_key} vanished during insert"
                raise RuntimeError(msg)
            return row_to_episode(existing)

    async def set_survived_latency(self, episode_id: int, survived: bool) -> None:
        """Single-column update so it cannot race with full-state saves."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(OpportunityEpisodeRow)
                .where(OpportunityEpisodeRow.id == episode_id)
                .values(survived_latency=survived)
            )

    async def save(self, episodes: Sequence[OpportunityEpisode]) -> None:
        """Persist mutable state; rows that are already closed are left untouched."""
        if not episodes:
            return
        async with self._sessions.begin() as session:
            for episode in episodes:
                if episode.id is None:
                    msg = "cannot save an episode without an id"
                    raise ValueError(msg)
                await session.execute(
                    update(OpportunityEpisodeRow)
                    .where(
                        OpportunityEpisodeRow.id == episode.id,
                        OpportunityEpisodeRow.closed_at.is_(None),
                    )
                    .values(**_episode_state(episode))
                )

    async def list_open(self) -> list[OpportunityEpisode]:
        """All episodes that are not closed."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(OpportunityEpisodeRow).where(OpportunityEpisodeRow.closed_at.is_(None))
            )
            return [row_to_episode(row) for row in rows]


class QuarantineRepository(_Repository, IQuarantineRepository):
    """Stores the quarantine history."""

    async def record_start(self, quarantine: RouteQuarantine) -> None:
        """Store a started quarantine."""
        async with self._sessions.begin() as session:
            session.add(
                RouteQuarantineRow(
                    symbol=quarantine.symbol,
                    buy_exchange=quarantine.buy_exchange,
                    sell_exchange=quarantine.sell_exchange,
                    reason=quarantine.reason.value,
                    note=quarantine.note[:2000],
                    started_at=ms_to_datetime(quarantine.started_at_ms),
                    expires_at=ms_to_datetime(quarantine.expires_at_ms),
                )
            )

    async def record_lift(self, route_key: str, at_ms: int) -> None:
        """Mark the route's active quarantine row as lifted."""
        symbol, _, legs = route_key.partition("|")
        buy_exchange, _, sell_exchange = legs.partition(">")
        at = ms_to_datetime(at_ms)
        async with self._sessions.begin() as session:
            await session.execute(
                update(RouteQuarantineRow)
                .where(
                    RouteQuarantineRow.symbol == symbol,
                    RouteQuarantineRow.buy_exchange == buy_exchange,
                    RouteQuarantineRow.sell_exchange == sell_exchange,
                    RouteQuarantineRow.lifted_at.is_(None),
                    RouteQuarantineRow.expires_at > at,
                )
                .values(lifted_at=at)
            )


def _trade_row(portfolio_id: str, outcome: TradeOutcome, episode_id: int | None) -> PaperTradeRow:
    bd = outcome.breakdown if outcome.executed else None
    return PaperTradeRow(
        portfolio_id=portfolio_id,
        executed_at=ms_to_datetime(outcome.at_ms),
        episode_id=episode_id,
        symbol=outcome.symbol,
        base=outcome.base,
        buy_exchange=outcome.buy_exchange,
        sell_exchange=outcome.sell_exchange,
        executed=outcome.executed,
        skip_reason=outcome.skip_reason.value if outcome.skip_reason else None,
        cost_quote=bd.cost_quote if bd else None,
        proceeds_quote=bd.proceeds_quote if bd else None,
        base_bought=bd.base_bought if bd else None,
        base_sold=bd.base_sold if bd else None,
        net_usd=bd.net_profit_usd if bd else None,
        net_pct=bd.net_profit_pct if bd else None,
    )


def _rebalance_values(portfolio_id: str, rebalance: Rebalance) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "asset": rebalance.asset,
        "from_exchange": rebalance.from_exchange,
        "to_exchange": rebalance.to_exchange,
        "amount": rebalance.amount,
        "fee": rebalance.fee,
        "fee_usd": rebalance.fee_usd,
        "network": rebalance.network,
        "status": rebalance.status.value,
        "note": rebalance.note[:2000],
        "started_at": ms_to_datetime(rebalance.started_at_ms),
        "arrives_at": ms_to_datetime(rebalance.arrives_at_ms),
    }


def _row_to_rebalance(row: PaperRebalanceRow) -> Rebalance:
    return Rebalance(
        asset=row.asset,
        from_exchange=row.from_exchange,
        to_exchange=row.to_exchange,
        amount=row.amount,
        fee=row.fee,
        fee_usd=row.fee_usd,
        network=row.network,
        started_at_ms=datetime_to_ms(row.started_at),
        arrives_at_ms=datetime_to_ms(row.arrives_at),
        status=RebalanceStatus(row.status),
        note=row.note or "",
        id=row.id,
    )


class PaperRepository(_Repository, IPaperRepository):
    """Paper trades, virtual rebalances and balance snapshots."""

    async def commit(
        self,
        *,
        portfolio_id: str,
        at_ms: int,
        trades: Sequence[tuple[TradeOutcome, int | None]],
        rebalances: Sequence[Rebalance],
        holdings: Sequence[PaperHolding],
    ) -> list[Rebalance]:
        """One transaction: a crash can never persist a transfer without its balances."""
        stored: list[Rebalance] = []
        async with self._sessions.begin() as session:
            session.add_all(
                _trade_row(portfolio_id, outcome, episode_id) for outcome, episode_id in trades
            )
            for rebalance in rebalances:
                if rebalance.id is None:
                    row = PaperRebalanceRow(**_rebalance_values(portfolio_id, rebalance))
                    session.add(row)
                    await session.flush()
                    stored.append(replace(rebalance, id=row.id))
                else:
                    await session.execute(
                        update(PaperRebalanceRow)
                        .where(
                            PaperRebalanceRow.id == rebalance.id,
                            PaperRebalanceRow.portfolio_id == portfolio_id,
                        )
                        .values(status=rebalance.status.value)
                    )
                    stored.append(rebalance)
            captured_at = ms_to_datetime(at_ms)
            session.add_all(
                PaperBalanceSnapshotRow(
                    portfolio_id=portfolio_id,
                    captured_at=captured_at,
                    exchange=h.exchange,
                    asset=h.asset,
                    amount=h.amount,
                    seed_amount=h.seed.amount if h.seed else None,
                    seed_price=h.seed.price if h.seed else None,
                    price_usd=h.price_usd,
                )
                for h in holdings
            )
        return stored

    async def ensure_run(
        self, portfolio_id: str, definition: RunDefinition, now_ms: int
    ) -> PortfolioRun:
        """Resume the latest run when its definition hash matches, else start a new run."""
        async with self._sessions.begin() as session:
            latest = await session.scalar(
                select(PaperPortfolioRow)
                .where(PaperPortfolioRow.portfolio_id == portfolio_id)
                .order_by(PaperPortfolioRow.id.desc())
                .limit(1)
            )
            if latest is not None and latest.config_hash == definition.config_hash:
                return PortfolioRun(
                    portfolio_id, latest.id, datetime_to_ms(latest.started_at), definition
                )
            row = PaperPortfolioRow(
                portfolio_id=portfolio_id,
                started_at=ms_to_datetime(now_ms),
                venues=",".join(definition.venues),
                capital_usd=definition.capital_usd,
                config_hash=definition.config_hash,
            )
            session.add(row)
            await session.flush()
            return PortfolioRun(
                portfolio_id,
                row.id,
                now_ms,
                definition,
                created=True,
                previous_hash=latest.config_hash if latest is not None else None,
            )

    async def add_cap_stats(self, deltas: Sequence[CapStatsDelta]) -> None:
        """Additive upsert of the hourly cap-binding counters."""
        if not deltas:
            return
        async with self._sessions.begin() as session:
            for d in deltas:
                insert = pg_insert(PaperCapStatsRow).values(
                    portfolio_id=d.portfolio_id,
                    hour=ms_to_datetime(d.hour_ms),
                    sweeps=d.sweeps,
                    sweeps_cap_bound=d.sweeps_cap_bound,
                    dropped_routes=d.dropped_routes,
                    alerts_cap_excluded=d.alerts_cap_excluded,
                )
                table = PaperCapStatsRow.__table__
                await session.execute(
                    insert.on_conflict_do_update(
                        index_elements=[PaperCapStatsRow.portfolio_id, PaperCapStatsRow.hour],
                        set_={
                            "sweeps": table.c.sweeps + insert.excluded.sweeps,
                            "sweeps_cap_bound": table.c.sweeps_cap_bound
                            + insert.excluded.sweeps_cap_bound,
                            "dropped_routes": table.c.dropped_routes
                            + insert.excluded.dropped_routes,
                            "alerts_cap_excluded": table.c.alerts_cap_excluded
                            + insert.excluded.alerts_cap_excluded,
                        },
                    )
                )

    async def load_state(self, portfolio_id: str, since_ms: int = 0) -> PaperState | None:
        """Latest snapshot set + open transfers + totals of one portfolio's current run
        (rows before ``since_ms`` belong to an earlier run and are ignored)."""
        snap, trade, rebal = PaperBalanceSnapshotRow, PaperTradeRow, PaperRebalanceRow
        since = ms_to_datetime(since_ms)
        async with self._sessions() as session:
            latest = await session.scalar(
                select(func.max(snap.captured_at)).where(
                    snap.portfolio_id == portfolio_id, snap.captured_at >= since
                )
            )
            if latest is None:
                return None
            rows = await session.scalars(
                select(snap).where(snap.portfolio_id == portfolio_id, snap.captured_at == latest)
            )
            holdings = [
                PaperHolding(
                    exchange=r.exchange,
                    asset=r.asset,
                    amount=r.amount,
                    seed=Seed(r.seed_amount, r.seed_price)
                    if r.seed_amount is not None and r.seed_price is not None
                    else None,
                    price_usd=r.price_usd,
                )
                for r in rows
            ]
            open_rows = await session.scalars(
                select(rebal).where(
                    rebal.portfolio_id == portfolio_id,
                    rebal.started_at >= since,
                    rebal.status == RebalanceStatus.IN_FLIGHT.value,
                )
            )
            in_flight = [_row_to_rebalance(r) for r in open_rows]
            realized = await session.scalar(
                select(func.coalesce(func.sum(trade.net_usd), 0)).where(
                    trade.portfolio_id == portfolio_id,
                    trade.executed_at >= since,
                    trade.executed.is_(True),
                )
            )
            costs = await session.scalar(
                select(func.coalesce(func.sum(rebal.fee_usd), 0)).where(
                    rebal.portfolio_id == portfolio_id,
                    rebal.started_at >= since,
                    rebal.status != RebalanceStatus.BLOCKED.value,
                )
            )
        return PaperState(
            holdings=holdings,
            in_flight=in_flight,
            realized=Decimal(realized or 0),
            rebalance_costs=Decimal(costs or 0),
        )


class AlertLogRepository(_Repository, IAlertLogRepository):
    """Alert delivery log (one row per evaluation)."""

    async def claim(self, evaluation_id: int, *, channel: str) -> bool:
        """Atomically mark ``evaluation_id`` as being sent (see the interface docstring)."""
        insert = pg_insert(AlertLogRow).values(
            evaluation_id=evaluation_id,
            channel=channel,
            status=AlertDeliveryStatus.SENDING.value,
        )
        stmt = insert.on_conflict_do_update(
            index_elements=[AlertLogRow.evaluation_id],
            set_={
                "status": AlertDeliveryStatus.SENDING.value,
                "error": None,
                "updated_at": datetime.now(tz=UTC),
            },
            where=AlertLogRow.status == AlertDeliveryStatus.FAILED.value,
        ).returning(AlertLogRow.id)
        async with self._sessions.begin() as session:
            claimed = await session.scalar(stmt)
        return claimed is not None

    async def record(
        self,
        evaluation_id: int,
        *,
        channel: str,
        status: AlertDeliveryStatus,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Insert or update the delivery record of ``evaluation_id``."""
        values = {
            "evaluation_id": evaluation_id,
            "channel": channel,
            "status": status.value,
            "message_id": message_id,
            "error": error[:2000] if error else None,
        }
        stmt = pg_insert(AlertLogRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[AlertLogRow.evaluation_id],
            set_={
                "status": stmt.excluded.status,
                "message_id": stmt.excluded.message_id,
                "error": stmt.excluded.error,
                "updated_at": datetime.now(tz=UTC),
            },
        )
        async with self._sessions.begin() as session:
            await session.execute(stmt)


class ExchangeHealthRepository(_Repository, IExchangeHealthRepository):
    """Stores exchange call outcomes."""

    async def record(
        self,
        exchange: str,
        operation: str,
        *,
        ok: bool,
        latency_ms: int | None,
        error: str | None = None,
    ) -> None:
        """Store one call outcome."""
        async with self._sessions.begin() as session:
            session.add(
                ExchangeHealthRow(
                    checked_at=datetime.now(tz=UTC),
                    exchange=exchange,
                    operation=operation[:64],
                    ok=ok,
                    latency_ms=latency_ms,
                    error=error[:2000] if error else None,
                )
            )


class MetadataStatsRepository(_Repository, IMetadataStatsRepository):
    """Stores per-refresh metadata statistics."""

    async def record(self, at_ms: int, stats: Sequence[ExchangeMetadataStats]) -> None:
        """Store the stats of one refresh."""
        if not stats:
            return
        captured_at = ms_to_datetime(at_ms)
        async with self._sessions.begin() as session:
            session.add_all(
                ExchangeMetadataStatsRow(
                    captured_at=captured_at,
                    exchange=s.exchange,
                    markets=s.markets,
                    transfer_coverage_pct=s.transfer_coverage_pct,
                )
                for s in stats
            )


_TOP_EPISODES = 5
_QUARANTINES_LISTED = 10


def trade_free_clause(conditional: Collection[str]) -> ColumnElement[bool]:
    """WHERE: paper trade touching no conditional venue (either leg excludes it)."""
    names = tuple(conditional)
    return ~or_(PaperTradeRow.buy_exchange.in_(names), PaperTradeRow.sell_exchange.in_(names))


def rebalance_free_clause(conditional: Collection[str]) -> ColumnElement[bool]:
    """WHERE: paper transfer whose from/to venues are both non-conditional."""
    names = tuple(conditional)
    return ~or_(
        PaperRebalanceRow.from_exchange.in_(names), PaperRebalanceRow.to_exchange.in_(names)
    )


class DigestRepository(_Repository, IDigestRepository):
    """Read-only aggregates for the daily digest."""

    def __init__(
        self,
        sessions: Sessions,
        conditional_venues: Collection[str] = (),
        coverage_min_sweeps_per_hour: int = 60,
        expected_sweeps_per_hour: int | None = None,
    ) -> None:
        super().__init__(sessions)
        self._conditional = tuple(conditional_venues)
        self._min_sweeps = coverage_min_sweeps_per_hour
        self._expected_sweeps = expected_sweeps_per_hour

    async def collect(self, since_ms: int, until_ms: int) -> DigestData:
        """Aggregate the window ``[since_ms, until_ms)``."""
        since, until = ms_to_datetime(since_ms), ms_to_datetime(until_ms)
        async with self._sessions() as session:
            episodes = await self._episodes(session, since, until, self._conditional)
            unverified = await session.scalar(
                select(func.count()).where(
                    SpreadEvaluationRow.evaluated_at >= since,
                    SpreadEvaluationRow.evaluated_at < until,
                    SpreadEvaluationRow.status == EvaluationStatus.TRANSFER_UNVERIFIED.value,
                )
            )
            paper = await self._paper(session, since, until, self._conditional)
            portfolios = await self._portfolios(session, since, until)
            quarantines, active = await self._quarantines(session, since, until)
            uptime = await self._uptime(session, since, until)
            coverage = await self._coverage(session, until)
            set_coverage = await self._set_coverage(session, since_ms, until_ms)
        return DigestData(
            window_start_ms=since_ms,
            window_end_ms=until_ms,
            episodes=episodes,
            paper=paper,
            quarantines=quarantines,
            active_quarantines=active,
            uptime_pct=uptime,
            coverage_pct=coverage,
            conditional_venues=self._conditional,
            unverified_evaluations=int(unverified or 0),
            portfolios=portfolios,
            coverage=set_coverage,
        )

    async def _set_coverage(
        self, session: AsyncSession, since_ms: int, until_ms: int
    ) -> tuple[SetCoverage, ...]:
        """Scanner downtime per venue set from the hourly ``paper_cap_stats.sweeps`` counters."""
        stats = PaperCapStatsRow
        first_seen = {
            pid: datetime_to_ms(first)
            for pid, first in (
                await session.execute(
                    select(stats.portfolio_id, func.min(stats.hour)).group_by(stats.portfolio_id)
                )
            ).all()
        }
        by_hour: dict[str, dict[int, int]] = {}
        rows = await session.execute(
            select(stats.portfolio_id, stats.hour, stats.sweeps).where(
                stats.hour >= ms_to_datetime(since_ms - HOUR_MS),
                stats.hour < ms_to_datetime(until_ms),
            )
        )
        for pid, hour, sweeps in rows.all():
            by_hour.setdefault(pid, {})[datetime_to_ms(hour)] = int(sweeps)
        return compute_set_coverage(
            by_hour, first_seen, since_ms, until_ms, self._min_sweeps, self._expected_sweeps
        )

    @staticmethod
    async def _portfolios(
        session: AsyncSession, since: datetime, until: datetime
    ) -> tuple[PortfolioSummary, ...]:
        """Per shadow portfolio: current run start (``since``, from the registry, never from the
        purged snapshots), trade count and hedged P&L of that run."""
        run, trade, rebal = PaperPortfolioRow, PaperTradeRow, PaperRebalanceRow
        runs: dict[str, PaperPortfolioRow] = {}
        run_counts: dict[str, int] = {}
        for row in (
            await session.scalars(select(run).where(run.started_at < until).order_by(run.id))
        ).all():
            runs[row.portfolio_id] = row  # the latest run of a name wins
            run_counts[row.portfolio_id] = run_counts.get(row.portfolio_id, 0) + 1
        summaries = []
        for pid, current in runs.items():
            count, net = (
                await session.execute(
                    select(func.count(), func.coalesce(func.sum(trade.net_usd), 0)).where(
                        trade.portfolio_id == pid,
                        trade.executed.is_(True),
                        trade.executed_at >= current.started_at,
                        trade.executed_at < until,
                    )
                )
            ).one()
            fees = await session.scalar(
                select(func.coalesce(func.sum(rebal.fee_usd), 0)).where(
                    rebal.portfolio_id == pid,
                    rebal.status != RebalanceStatus.BLOCKED.value,
                    rebal.started_at >= current.started_at,
                    rebal.started_at < until,
                )
            )
            summaries.append(
                PortfolioSummary(
                    portfolio_id=pid,
                    since_ms=datetime_to_ms(current.started_at),
                    trades=int(count),
                    hedged_pnl_usd=Decimal(net or 0) - Decimal(fees or 0),
                    restarted=run_counts[pid] > 1 and current.started_at >= since,
                )
            )
        summaries.sort(key=lambda p: (p.portfolio_id != DEFAULT_PORTFOLIO_ID, p.portfolio_id))
        return tuple(summaries)

    @staticmethod
    async def _episodes(
        session: AsyncSession, since: datetime, until: datetime, conditional: Collection[str]
    ) -> EpisodeStats:
        rows = (
            await session.scalars(
                select(OpportunityEpisodeRow).where(
                    OpportunityEpisodeRow.opened_at >= since,
                    OpportunityEpisodeRow.opened_at < until,
                )
            )
        ).all()
        if not rows:
            return EpisodeStats(total_excl_conditional=0)  # quiet day: 0, not "unknown"
        quarantined = [r for r in rows if r.close_reason == EpisodeCloseReason.QUARANTINED.value]
        rest = [r for r in rows if r.close_reason != EpisodeCloseReason.QUARANTINED.value]
        verified = sum(1 for r in rest if r.transfer_status == TransferStatus.VERIFIED.value)
        durations = sorted(int((r.last_seen_at - r.opened_at).total_seconds()) for r in rows)
        top = sorted(rows, key=lambda r: r.peak_net_usd, reverse=True)[:_TOP_EPISODES]
        return EpisodeStats(
            total=len(rows),
            total_excl_conditional=sum(
                1
                for r in rows
                if not touches_conditional(r.buy_exchange, r.sell_exchange, conditional)
            ),
            verified=verified,
            unverified=len(rest) - verified,
            quarantined=len(quarantined),
            survived_latency=sum(1 for r in rows if r.survived_latency is True),
            latency_checked=sum(1 for r in rows if r.survived_latency is not None),
            median_duration_s=int(statistics.median(durations)),
            max_duration_s=durations[-1],
            top=tuple(
                EpisodeSummary(
                    symbol=r.symbol,
                    buy_exchange=r.buy_exchange,
                    sell_exchange=r.sell_exchange,
                    peak_net_usd=r.peak_net_usd,
                    peak_net_pct=r.peak_net_pct,
                    duration_s=int((r.last_seen_at - r.opened_at).total_seconds()),
                    survived_latency=r.survived_latency,
                )
                for r in top
            ),
        )

    @staticmethod
    async def _paper(
        session: AsyncSession, since: datetime, until: datetime, conditional: Collection[str]
    ) -> PaperStats | None:
        # Every query is bounded by the current run of the default set: rows of an earlier
        # definition (incl. a never-restored IN_FLIGHT rebalance) must not leak into the totals.
        run_start = await session.scalar(
            select(PaperPortfolioRow.started_at)
            .where(
                PaperPortfolioRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
                PaperPortfolioRow.started_at < until,
            )
            .order_by(PaperPortfolioRow.id.desc())
            .limit(1)
        )
        if run_start is None:
            run_start = datetime.min.replace(tzinfo=UTC)
        since = max(since, run_start)
        latest = await session.scalar(
            select(func.max(PaperBalanceSnapshotRow.captured_at)).where(
                PaperBalanceSnapshotRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
                PaperBalanceSnapshotRow.captured_at < until,
                PaperBalanceSnapshotRow.captured_at >= run_start,
            )
        )
        if latest is None:
            return None
        holdings = (
            await session.scalars(
                select(PaperBalanceSnapshotRow).where(
                    PaperBalanceSnapshotRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
                    PaperBalanceSnapshotRow.captured_at == latest,
                )
            )
        ).all()
        prices = {h.asset: h.price_usd for h in holdings if h.price_usd is not None}
        capital = sum(
            (h.seed_amount * h.seed_price for h in holdings if h.seed_amount and h.seed_price),
            Decimal(0),
        )
        equity = sum(
            (
                h.amount * (h.price_usd if h.price_usd is not None else h.seed_price or 0)
                for h in holdings
            ),
            Decimal(0),
        )
        in_flight = (
            await session.scalars(
                select(PaperRebalanceRow).where(
                    PaperRebalanceRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
                    PaperRebalanceRow.status == RebalanceStatus.IN_FLIGHT.value,
                    PaperRebalanceRow.started_at >= run_start,
                )
            )
        ).all()
        equity += sum(
            ((r.amount - r.fee) * (prices.get(r.asset) or 0) for r in in_flight), Decimal(0)
        )
        window_trades = (
            PaperTradeRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
            PaperTradeRow.executed_at >= since,
            PaperTradeRow.executed_at < until,
        )
        trades = await session.scalar(
            select(func.count()).where(*window_trades, PaperTradeRow.executed.is_(True))
        )
        skipped = {
            str(reason): int(count)
            for reason, count in (
                await session.execute(
                    select(PaperTradeRow.skip_reason, func.count())
                    .where(*window_trades, PaperTradeRow.executed.is_(False))
                    .group_by(PaperTradeRow.skip_reason)
                )
            ).all()
        }
        realized = await session.scalar(
            select(func.coalesce(func.sum(PaperTradeRow.net_usd), 0)).where(
                *window_trades, PaperTradeRow.executed.is_(True)
            )
        )
        window_rebalances = (
            PaperRebalanceRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
            PaperRebalanceRow.started_at >= since,
            PaperRebalanceRow.started_at < until,
        )
        moved = and_(
            PaperRebalanceRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
            PaperRebalanceRow.status != RebalanceStatus.BLOCKED.value,
            PaperRebalanceRow.started_at >= run_start,
        )
        own_trades = and_(
            PaperTradeRow.portfolio_id == DEFAULT_PORTFOLIO_ID,
            PaperTradeRow.executed.is_(True),
            PaperTradeRow.executed_at >= run_start,
        )
        rebalance_usd = await session.scalar(
            select(func.coalesce(func.sum(PaperRebalanceRow.fee_usd), 0)).where(
                *window_rebalances, moved
            )
        )
        rebalances = await session.scalar(select(func.count()).where(*window_rebalances, moved))
        blocked = await session.scalar(
            select(func.count()).where(
                *window_rebalances, PaperRebalanceRow.status == RebalanceStatus.BLOCKED.value
            )
        )
        realized_total = await session.scalar(
            select(func.coalesce(func.sum(PaperTradeRow.net_usd), 0)).where(own_trades)
        )
        rebalance_total = await session.scalar(
            select(func.coalesce(func.sum(PaperRebalanceRow.fee_usd), 0)).where(moved)
        )
        # Hedged P&L without conditional venues: trades and transfers where neither leg
        # (buy/sell, from/to) is a conditional venue. Equity/mark-to-market is not split.
        realized_excl = await session.scalar(
            select(func.coalesce(func.sum(PaperTradeRow.net_usd), 0)).where(
                own_trades, trade_free_clause(conditional)
            )
        )
        rebalance_excl = await session.scalar(
            select(func.coalesce(func.sum(PaperRebalanceRow.fee_usd), 0)).where(
                moved, rebalance_free_clause(conditional)
            )
        )
        return PaperStats(
            trades=int(trades or 0),
            skipped=skipped,
            realized_usd=Decimal(realized or 0),
            rebalance_usd=Decimal(rebalance_usd or 0),
            rebalances=int(rebalances or 0),
            blocked_rebalances=int(blocked or 0),
            capital_usd=capital,
            equity_usd=equity,
            realized_total_usd=Decimal(realized_total or 0),
            rebalance_total_usd=Decimal(rebalance_total or 0),
            realized_total_excl_conditional_usd=Decimal(realized_excl or 0),
            rebalance_total_excl_conditional_usd=Decimal(rebalance_excl or 0),
        )

    @staticmethod
    async def _quarantines(
        session: AsyncSession, since: datetime, until: datetime
    ) -> tuple[tuple[QuarantineSummary, ...], int]:
        started = (
            await session.scalars(
                select(RouteQuarantineRow)
                .where(
                    RouteQuarantineRow.started_at >= since, RouteQuarantineRow.started_at < until
                )
                .order_by(RouteQuarantineRow.started_at)
            )
        ).all()
        active = await session.scalar(
            select(func.count()).where(
                RouteQuarantineRow.started_at < until,
                RouteQuarantineRow.expires_at > until,
                RouteQuarantineRow.lifted_at.is_(None),
            )
        )
        listed = tuple(
            QuarantineSummary(r.symbol, r.buy_exchange, r.sell_exchange, r.reason) for r in started
        )
        return listed, int(active or 0)

    @staticmethod
    async def _uptime(
        session: AsyncSession, since: datetime, until: datetime
    ) -> dict[str, int | None]:
        rows = await session.execute(
            select(
                ExchangeHealthRow.exchange,
                func.count(),
                func.count().filter(ExchangeHealthRow.ok.is_(True)),
            )
            .where(ExchangeHealthRow.checked_at >= since, ExchangeHealthRow.checked_at < until)
            .group_by(ExchangeHealthRow.exchange)
        )
        return {
            str(exchange): int(ok) * 100 // int(total) if total else None
            for exchange, total, ok in rows.all()
        }

    @staticmethod
    async def _coverage(session: AsyncSession, until: datetime) -> dict[str, int | None]:
        latest = (
            select(
                ExchangeMetadataStatsRow.exchange,
                func.max(ExchangeMetadataStatsRow.captured_at).label("at"),
            )
            .where(ExchangeMetadataStatsRow.captured_at < until)
            .group_by(ExchangeMetadataStatsRow.exchange)
            .subquery()
        )
        rows = await session.execute(
            select(
                ExchangeMetadataStatsRow.exchange, ExchangeMetadataStatsRow.transfer_coverage_pct
            ).join(
                latest,
                (ExchangeMetadataStatsRow.exchange == latest.c.exchange)
                & (ExchangeMetadataStatsRow.captured_at == latest.c.at),
            )
        )
        return {str(exchange): pct for exchange, pct in rows.all()}


class RetentionRepository(_Repository, IRetentionRepository):
    """Deletes old analytics rows; profitable evaluations are kept indefinitely."""

    async def purge(
        self,
        *,
        snapshots_before: datetime,
        evaluations_before: datetime,
        episodes_before: datetime,
    ) -> dict[str, int]:
        """Delete rows past their retention window (see the interface for what is kept)."""
        async with self._sessions.begin() as session:
            # Old snapshot sets are thinned to the LAST set of each UTC day per portfolio (the
            # GO report needs a daily equity curve over the whole run, B15 spec B3/B5); the
            # latest set of every portfolio always survives (each has its own timeline).
            newer = aliased(PaperBalanceSnapshotRow)
            has_newer = (
                select(newer.id)
                .where(
                    newer.portfolio_id == PaperBalanceSnapshotRow.portfolio_id,
                    newer.captured_at > PaperBalanceSnapshotRow.captured_at,
                    func.date_trunc("day", func.timezone("UTC", newer.captured_at))
                    == func.date_trunc(
                        "day", func.timezone("UTC", PaperBalanceSnapshotRow.captured_at)
                    ),
                )
                .exists()
            )
            paper_snapshots = await session.execute(
                delete(PaperBalanceSnapshotRow).where(
                    PaperBalanceSnapshotRow.captured_at < snapshots_before, has_newer
                )
            )
            metadata_stats = await session.execute(
                delete(ExchangeMetadataStatsRow).where(
                    ExchangeMetadataStatsRow.captured_at < snapshots_before
                )
            )
            episodes = await session.execute(
                delete(OpportunityEpisodeRow).where(
                    OpportunityEpisodeRow.closed_at.is_not(None),
                    OpportunityEpisodeRow.closed_at < episodes_before,
                )
            )
            quarantines = await session.execute(
                delete(RouteQuarantineRow).where(RouteQuarantineRow.expires_at < episodes_before)
            )
            snapshots = await session.execute(
                delete(SpreadSnapshotRow).where(SpreadSnapshotRow.captured_at < snapshots_before)
            )
            health = await session.execute(
                delete(ExchangeHealthRow).where(ExchangeHealthRow.checked_at < snapshots_before)
            )
            evaluations = await session.execute(
                delete(SpreadEvaluationRow).where(
                    SpreadEvaluationRow.evaluated_at < evaluations_before,
                    SpreadEvaluationRow.status != EvaluationStatus.PROFITABLE.value,
                )
            )
        return {
            "spread_snapshots": _rowcount(snapshots),
            "exchange_health": _rowcount(health),
            "spread_evaluations": _rowcount(evaluations),
            "paper_balance_snapshots": _rowcount(paper_snapshots),
            "exchange_metadata_stats": _rowcount(metadata_stats),
            "opportunity_episodes": _rowcount(episodes),
            "route_quarantine": _rowcount(quarantines),
        }


def _rowcount(result: Any) -> int:
    """``CursorResult.rowcount`` (``Any``: execute() is typed as the generic Result)."""
    count = getattr(result, "rowcount", 0)
    return int(count) if isinstance(count, int) and count >= 0 else 0


__all__ = [
    "AlertLogRepository",
    "EvaluationRepository",
    "ExchangeHealthRepository",
    "MarketRepository",
    "RetentionRepository",
    "SnapshotRepository",
    "evaluation_to_row",
    "row_to_evaluation",
]


class ScannerActivityRepository(_Repository, IScannerActivity):
    """Latest recorded exchange call = the scanner is sweeping (primary-key index, O(1))."""

    async def last_activity_ms(self) -> int | None:
        """Epoch ms of the newest ``exchange_health`` row, ``None`` if the table is empty."""
        async with self._sessions() as session:
            checked_at = await session.scalar(
                select(ExchangeHealthRow.checked_at).order_by(ExchangeHealthRow.id.desc()).limit(1)
            )
        return None if checked_at is None else datetime_to_ms(checked_at)


class PaperSetActivityRepository(_Repository, IPaperSetActivity):
    """Venue sets from the run registry with their newest ``paper_cap_stats`` hour (read-only)."""

    async def read(self) -> dict[str, PaperSetActivity]:
        """Current run start and newest stats hour per registered set (two small aggregates)."""
        async with self._sessions() as session:
            runs = (
                await session.execute(
                    select(
                        PaperPortfolioRow.portfolio_id, func.max(PaperPortfolioRow.started_at)
                    ).group_by(PaperPortfolioRow.portfolio_id)
                )
            ).all()
            hour_rows = (
                await session.execute(
                    select(PaperCapStatsRow.portfolio_id, func.max(PaperCapStatsRow.hour)).group_by(
                        PaperCapStatsRow.portfolio_id
                    )
                )
            ).all()
            hours = dict(hour_rows)
        return {
            pid: PaperSetActivity(
                datetime_to_ms(started),
                None if (hour := hours.get(pid)) is None else datetime_to_ms(hour),
            )
            for pid, started in runs
        }
