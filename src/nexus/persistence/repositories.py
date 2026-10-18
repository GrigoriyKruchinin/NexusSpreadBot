"""PostgreSQL repository implementations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    async def add_evaluations(self, evaluations: Sequence[SpreadEvaluation]) -> list[int]:
        """Store evaluations; returns their ids in input order."""
        if not evaluations:
            return []
        rows = [evaluation_to_row(e) for e in evaluations]
        async with self._sessions.begin() as session:
            session.add_all(rows)
            await session.flush()
            return [row.id for row in rows]

    async def get(self, evaluation_id: int) -> SpreadEvaluation | None:
        """Load one evaluation by id."""
        async with self._sessions() as session:
            row = await session.get(SpreadEvaluationRow, evaluation_id)
            return row_to_evaluation(row) if row is not None else None


class AlertLogRepository(_Repository, IAlertLogRepository):
    """Alert delivery log (one row per evaluation)."""

    async def was_sent(self, evaluation_id: int) -> bool:
        """True if an alert for ``evaluation_id`` was already delivered."""
        async with self._sessions() as session:
            status = await session.scalar(
                select(AlertLogRow.status).where(AlertLogRow.evaluation_id == evaluation_id)
            )
            return status == AlertDeliveryStatus.SENT.value

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
