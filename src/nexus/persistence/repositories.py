"""PostgreSQL repository implementations."""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.conditional import touches_conditional
from nexus.domain.digest import (
    DigestData,
    EpisodeStats,
    EpisodeSummary,
    QuarantineSummary,
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
    EpisodeMessage,
    ExchangeMetadataStats,
    IAlertLogRepository,
    IAlertMessageRepository,
    IDigestRepository,
    IEpisodeRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    IMetadataStatsRepository,
    IQuarantineRepository,
    IRetentionRepository,
    ISnapshotRepository,
    SuppressedSummary,
)
from nexus.interfaces.watchdog import IScannerActivity
from nexus.persistence.models import (
    AlertHourBudgetRow,
    AlertLogRow,
    ExchangeHealthRow,
    ExchangeMetadataStatsRow,
    MarketPairRow,
    OpportunityEpisodeRow,
    RouteQuarantineRow,
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


STALE_SENDING_ERROR = "reaped: stuck in sending (worker died between claim and result)"


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


class AlertMessageRepository(_Repository, IAlertMessageRepository):
    """Episode message ids (columns of ``opportunity_episodes`` that only the alerts worker
    writes, so the scanner's state saves cannot clobber them) and the hourly NEW budget."""

    async def get_episode_message(self, episode_id: int) -> EpisodeMessage | None:
        """The message of ``episode_id`` or ``None``."""
        async with self._sessions() as session:
            row = await session.get(OpportunityEpisodeRow, episode_id)
        if row is None or row.alert_message_id is None or row.alert_evaluation_id is None:
            return None
        return EpisodeMessage(
            episode_id=episode_id,
            message_id=row.alert_message_id,
            evaluation_id=row.alert_evaluation_id,
            context=dict(row.alert_context or {}),
        )

    async def save_episode_message(
        self, episode_id: int, *, message_id: str, evaluation_id: int, context: dict[str, Any]
    ) -> None:
        """Store the episode's message (also for an already closed episode)."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(OpportunityEpisodeRow)
                .where(OpportunityEpisodeRow.id == episode_id)
                .values(
                    alert_message_id=message_id,
                    alert_evaluation_id=evaluation_id,
                    alert_context=context,
                )
            )

    async def try_consume(self, window_start_ms: int, limit: int) -> bool:
        """Atomically take a slot: the increment only happens below ``limit``."""
        insert = pg_insert(AlertHourBudgetRow).values(
            window_start=ms_to_datetime(window_start_ms), sent=1
        )
        stmt = insert.on_conflict_do_update(
            index_elements=[AlertHourBudgetRow.window_start],
            set_={"sent": AlertHourBudgetRow.sent + 1},
            where=AlertHourBudgetRow.sent < limit,
        ).returning(AlertHourBudgetRow.sent)
        async with self._sessions.begin() as session:
            return await session.scalar(stmt) is not None

    async def refund(self, window_start_ms: int) -> None:
        """Release a slot (never below zero)."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(AlertHourBudgetRow)
                .where(
                    AlertHourBudgetRow.window_start == ms_to_datetime(window_start_ms),
                    AlertHourBudgetRow.sent > 0,
                )
                .values(sent=AlertHourBudgetRow.sent - 1)
            )

    async def record_suppressed(self, window_start_ms: int) -> SuppressedSummary:
        """Count one suppression and read the window's total and summary message id."""
        insert = pg_insert(AlertHourBudgetRow).values(
            window_start=ms_to_datetime(window_start_ms), suppressed=1
        )
        stmt = insert.on_conflict_do_update(
            index_elements=[AlertHourBudgetRow.window_start],
            set_={"suppressed": AlertHourBudgetRow.suppressed + 1},
        ).returning(AlertHourBudgetRow.suppressed, AlertHourBudgetRow.summary_message_id)
        async with self._sessions.begin() as session:
            row = (await session.execute(stmt)).one()
        return SuppressedSummary(suppressed=row.suppressed, message_id=row.summary_message_id)

    async def set_summary_message(self, window_start_ms: int, message_id: str) -> None:
        """Remember the summary message of the window."""
        async with self._sessions.begin() as session:
            await session.execute(
                update(AlertHourBudgetRow)
                .where(AlertHourBudgetRow.window_start == ms_to_datetime(window_start_ms))
                .values(summary_message_id=message_id)
            )


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


class DigestRepository(_Repository, IDigestRepository):
    """Read-only aggregates for the daily digest."""

    def __init__(
        self,
        sessions: Sessions,
        conditional_venues: Collection[str] = (),
    ) -> None:
        super().__init__(sessions)
        self._conditional = tuple(conditional_venues)

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
            quarantines, active = await self._quarantines(session, since, until)
            uptime = await self._uptime(session, since, until)
            coverage = await self._coverage(session, until)
        return DigestData(
            window_start_ms=since_ms,
            window_end_ms=until_ms,
            episodes=episodes,
            quarantines=quarantines,
            active_quarantines=active,
            uptime_pct=uptime,
            coverage_pct=coverage,
            conditional_venues=self._conditional,
            unverified_evaluations=int(unverified or 0),
        )

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
        alerts_sending_before: datetime | None = None,
    ) -> dict[str, int]:
        """Delete rows past their retention window (see the interface for what is kept)."""
        async with self._sessions.begin() as session:
            reaped = (
                await session.execute(
                    update(AlertLogRow)
                    .where(
                        AlertLogRow.status == AlertDeliveryStatus.SENDING.value,
                        AlertLogRow.updated_at < alerts_sending_before,
                    )
                    .values(status=AlertDeliveryStatus.FAILED.value, error=STALE_SENDING_ERROR)
                )
                if alerts_sending_before is not None
                else None
            )
            budgets = await session.execute(
                delete(AlertHourBudgetRow).where(AlertHourBudgetRow.window_start < episodes_before)
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
            "exchange_metadata_stats": _rowcount(metadata_stats),
            "opportunity_episodes": _rowcount(episodes),
            "route_quarantine": _rowcount(quarantines),
            "alert_hour_budget": _rowcount(budgets),
            "alert_log_stale_sending": _rowcount(reaped) if reaped is not None else 0,
        }


def _rowcount(result: Any) -> int:
    """``CursorResult.rowcount`` (``Any``: execute() is typed as the generic Result)."""
    count = getattr(result, "rowcount", 0)
    return int(count) if isinstance(count, int) and count >= 0 else 0


__all__ = [
    "AlertLogRepository",
    "AlertMessageRepository",
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
