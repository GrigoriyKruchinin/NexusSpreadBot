from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.models import MarketInfo
from nexus.domain.spread import EvaluationStatus
from nexus.engine.candidates import RouteQuote
from nexus.interfaces.repositories import AlertDeliveryStatus
from nexus.persistence.models import (
    AlertLogRow,
    ExchangeHealthRow,
    MarketPairRow,
    SpreadSnapshotRow,
)
from nexus.persistence.repositories import (
    STALE_SENDING_ERROR,
    AlertLogRepository,
    AlertMessageRepository,
    EpisodeRepository,
    EvaluationRepository,
    ExchangeHealthRepository,
    MarketRepository,
    RetentionRepository,
    SnapshotRepository,
    ms_to_datetime,
)
from tests.support import make_evaluation

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]


async def test_market_upsert(sessions: Sessions) -> None:
    repo = MarketRepository(sessions)
    market = MarketInfo(
        exchange="okx",
        symbol="BTC/USDT",
        base="BTC",
        quote="USDT",
        taker_fee=D("0.001"),
        amount_step=D("0.00000001"),
    )
    assert await repo.upsert_markets([market]) == 1
    updated = MarketInfo(
        exchange="okx",
        symbol="BTC/USDT",
        base="BTC",
        quote="USDT",
        taker_fee=D("0.0008"),
        active=False,
    )
    await repo.upsert_markets([updated])
    async with sessions() as session:
        rows = (await session.scalars(select(MarketPairRow))).all()
    assert len(rows) == 1
    assert rows[0].taker_fee == D("0.0008")
    assert rows[0].active is False
    assert rows[0].amount_step is None


async def test_evaluation_roundtrip_exact_decimals(sessions: Sessions) -> None:
    repo = EvaluationRepository(sessions)
    evaluations = [
        make_evaluation(),
        make_evaluation(status=EvaluationStatus.STALE_BOOK, with_breakdown=False),
    ]
    ids = await repo.add_evaluations(evaluations)
    assert len(ids) == 2
    assert await repo.get(ids[0]) == evaluations[0]
    assert await repo.get(ids[1]) == evaluations[1]
    assert await repo.get(999_999) is None


async def test_alert_log_idempotency(sessions: Sessions) -> None:
    [evaluation_id] = await EvaluationRepository(sessions).add_evaluations([make_evaluation()])
    alerts = AlertLogRepository(sessions)
    assert await alerts.claim(evaluation_id, channel="telegram")
    assert not await alerts.claim(evaluation_id, channel="telegram")  # in flight
    await alerts.record(
        evaluation_id, channel="telegram", status=AlertDeliveryStatus.FAILED, error="timeout"
    )
    assert await alerts.claim(evaluation_id, channel="telegram")  # retry after failure
    await alerts.record(
        evaluation_id, channel="telegram", status=AlertDeliveryStatus.SENT, message_id="42"
    )
    assert not await alerts.claim(evaluation_id, channel="telegram")  # delivered


async def test_snapshots_health_and_retention(sessions: Sessions) -> None:
    now = datetime.now(tz=UTC)
    route = RouteQuote(
        symbol="ABC/USDT",
        buy_exchange="a",
        sell_exchange="b",
        ask=D(1),
        bid=D("1.01"),
        gross_spread_pct=D(1),
        fee_bound_net_pct=D("0.8"),
    )
    snapshots = SnapshotRepository(sessions)
    await snapshots.add_snapshots(now - timedelta(days=10), [route])
    await snapshots.add_snapshots(now, [route, route])
    await ExchangeHealthRepository(sessions).record("okx", "fetch_tickers", ok=True, latency_ms=80)

    evaluations = EvaluationRepository(sessions)
    old_ms = int((now - timedelta(days=40)).timestamp() * 1000)
    await evaluations.add_evaluations(
        [
            make_evaluation(evaluated_at_ms=old_ms),  # profitable: kept forever
            make_evaluation(status=EvaluationStatus.BELOW_THRESHOLD, evaluated_at_ms=old_ms),
            make_evaluation(status=EvaluationStatus.BELOW_THRESHOLD),
        ]
    )

    counts = await RetentionRepository(sessions).purge(
        snapshots_before=now - timedelta(days=7),
        evaluations_before=now - timedelta(days=30),
        episodes_before=now - timedelta(days=90),
    )
    assert counts == {
        "spread_snapshots": 1,
        "exchange_health": 0,
        "spread_evaluations": 1,
        "exchange_metadata_stats": 0,
        "opportunity_episodes": 0,
        "route_quarantine": 0,
    }
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SpreadSnapshotRow)) == 2
        assert await session.scalar(select(func.count()).select_from(ExchangeHealthRow)) == 1
    assert ms_to_datetime(old_ms).tzinfo is UTC


async def test_episode_message_and_hourly_budget(sessions: Sessions) -> None:
    episodes = EpisodeRepository(sessions)
    messages = AlertMessageRepository(sessions)
    stored = await episodes.open(OpportunityEpisode.open(make_evaluation()))
    assert stored.id is not None
    assert await messages.get_episode_message(stored.id) is None
    context = {"episode_id": stored.id, "realert": 1, "volume": {"max_quote": "950"}}
    await messages.save_episode_message(
        stored.id, message_id="42", evaluation_id=5, context=context
    )
    loaded = await messages.get_episode_message(stored.id)
    assert loaded is not None
    assert (loaded.message_id, loaded.evaluation_id, loaded.context) == ("42", 5, context)

    # The scanner's full-state save must not clobber the worker's columns, and a close keeps them.
    await episodes.save([replace(stored, evaluations=3)])
    await episodes.save([stored.close(stored.opened_at_ms + 1, EpisodeCloseReason.GAP)])
    assert (await messages.get_episode_message(stored.id)) == loaded

    window = 1_800_000_000_000 - 1_800_000_000_000 % 3_600_000
    assert [await messages.try_consume(window, 2) for _ in range(3)] == [True, True, False]
    await messages.refund(window)
    assert await messages.try_consume(window, 2)
    first = await messages.record_suppressed(window)
    assert (first.suppressed, first.message_id) == (1, None)
    await messages.set_summary_message(window, "99")
    second = await messages.record_suppressed(window)
    assert (second.suppressed, second.message_id) == (2, "99")
    # A window with only suppressions (no row yet) is created by the upsert.
    other = await messages.record_suppressed(window + 3_600_000)
    assert other.suppressed == 1


async def test_stale_sending_alert_rows_are_reaped(sessions: Sessions) -> None:
    stale_id, fresh_id, sent_id = await EvaluationRepository(sessions).add_evaluations(
        [make_evaluation(symbol=f"A{i}/USDT") for i in range(3)]
    )
    alerts = AlertLogRepository(sessions)
    for evaluation_id in (stale_id, fresh_id):
        assert await alerts.claim(evaluation_id, channel="telegram")
    await alerts.record(sent_id, channel="telegram", status=AlertDeliveryStatus.SENT)
    old = datetime.now(tz=UTC) - timedelta(hours=1)
    async with sessions.begin() as session:
        await session.execute(
            update(AlertLogRow)
            .where(AlertLogRow.evaluation_id.in_([stale_id, sent_id]))
            .values(updated_at=old)
        )
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=10)
    counts = await RetentionRepository(sessions).purge(
        snapshots_before=cutoff,
        evaluations_before=cutoff,
        episodes_before=cutoff,
        alerts_sending_before=cutoff,
    )
    assert counts["alert_log_stale_sending"] == 1
    async with sessions() as session:
        rows = {row.evaluation_id: row for row in await session.scalars(select(AlertLogRow))}
    assert rows[stale_id].status == "failed"
    assert rows[stale_id].error == STALE_SENDING_ERROR
    assert rows[fresh_id].status == "sending"  # still in flight
    assert rows[sent_id].status == "sent"  # finished rows are never touched
    assert await alerts.claim(stale_id, channel="telegram")  # a reaped row can be claimed again
