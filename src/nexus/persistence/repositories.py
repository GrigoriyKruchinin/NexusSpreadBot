"""PostgreSQL repository implementations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.models import MarketInfo
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
    IAlertLogRepository,
    IEpisodeRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    IRetentionRepository,
    ISnapshotRepository,
)
from nexus.persistence.models import (
    AlertLogRow,
    ExchangeHealthRow,
    MarketPairRow,
    OpportunityEpisodeRow,
    SpreadEvaluationRow,
    SpreadSnapshotRow,
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


class RetentionRepository(_Repository, IRetentionRepository):
    """Deletes old analytics rows; profitable evaluations are kept indefinitely."""

    async def purge(
        self, *, snapshots_before: datetime, evaluations_before: datetime
    ) -> dict[str, int]:
        """Delete old snapshots/health rows and non-profitable evaluations."""
        async with self._sessions.begin() as session:
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
