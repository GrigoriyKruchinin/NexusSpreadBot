from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.models import MarketInfo
from nexus.domain.spread import EvaluationStatus
from nexus.engine.candidates import RouteQuote
from nexus.interfaces.repositories import AlertDeliveryStatus
from nexus.persistence.models import ExchangeHealthRow, MarketPairRow, SpreadSnapshotRow
from nexus.persistence.repositories import (
    AlertLogRepository,
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
