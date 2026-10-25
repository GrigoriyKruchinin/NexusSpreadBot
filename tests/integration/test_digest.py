from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.domain.spread import EvaluationStatus, TransferQuote, TransferStatus
from nexus.interfaces.repositories import ExchangeMetadataStats
from nexus.persistence.models import OpportunityEpisodeRow
from nexus.persistence.repositories import (
    DigestRepository,
    EpisodeRepository,
    EvaluationRepository,
    ExchangeHealthRepository,
    MetadataStatsRepository,
    QuarantineRepository,
    RetentionRepository,
)
from tests.support import make_evaluation

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
H = 3_600_000
UNKNOWN = TransferQuote(TransferStatus.UNKNOWN)


async def _episode(repo: EpisodeRepository, **kw: object) -> OpportunityEpisode:
    opened = int(kw.pop("opened", T0))  # type: ignore[call-overload]
    seen = int(kw.pop("seen", opened))  # type: ignore[call-overload]
    evaluation = make_evaluation(evaluated_at_ms=opened, **kw)  # type: ignore[arg-type]
    episode = await repo.open(OpportunityEpisode.open(evaluation))
    return replace(episode, last_seen_at_ms=seen)


async def test_collect_digest(sessions: Sessions) -> None:
    episodes = EpisodeRepository(sessions)
    a = await _episode(episodes, opened=T0 + H, seen=T0 + H + 200_000, net_usd=D(12))
    b = await _episode(
        episodes,
        opened=T0 + 2 * H,
        seen=T0 + 2 * H + 60_000,
        symbol="UNV/USDT",
        status=EvaluationStatus.TRANSFER_UNVERIFIED,
        transfer=UNKNOWN,
    )
    c = await _episode(episodes, opened=T0 + 3 * H, symbol="ZIL/USDT", net_usd=D(6))
    await _episode(episodes, opened=T0 - 2 * H, symbol="OLD/USDT")  # outside the window
    await episodes.save(
        [
            replace(a, survived_latency=True),
            replace(b, survived_latency=False),
            c.close(T0 + 4 * H, EpisodeCloseReason.QUARANTINED),
        ]
    )
    await EvaluationRepository(sessions).add_evaluations(
        [make_evaluation(status=EvaluationStatus.TRANSFER_UNVERIFIED, evaluated_at_ms=T0 + H)]
    )
    await QuarantineRepository(sessions).record_start(
        RouteQuarantine(
            "ZIL/USDT",
            "binance",
            "okx",
            QuarantineReason.UNVERIFIED_PERSISTENT,
            T0 + H,
            T0 + 30 * H,
        )
    )
    stats = MetadataStatsRepository(sessions)
    await stats.record(T0, [ExchangeMetadataStats("okx", 400, 0)])
    await stats.record(T0 + H, [ExchangeMetadataStats("okx", 401, 87)])
    data = await DigestRepository(sessions).collect(T0, T0 + 24 * H)
    e = data.episodes
    assert (e.total, e.verified, e.unverified, e.quarantined) == (3, 1, 1, 1)
    assert (e.survived_latency, e.latency_checked) == (1, 2)
    assert (e.median_duration_s, e.max_duration_s) == (60, 200)
    assert [t.symbol for t in e.top] == ["ABC/USDT", "UNV/USDT", "ZIL/USDT"]
    assert data.unverified_evaluations == 1
    assert [q.symbol for q in data.quarantines] == ["ZIL/USDT"]
    assert data.active_quarantines == 1
    assert data.coverage_pct == {"okx": 87}


async def test_uptime_and_retention(sessions: Sessions) -> None:
    health = ExchangeHealthRepository(sessions)
    for ok in (True, True, True, False):
        await health.record("okx", "fetch_tickers", ok=ok, latency_ms=10)
    now = datetime.now(tz=UTC)
    now_ms = int(now.timestamp() * 1000)
    data = await DigestRepository(sessions).collect(now_ms - 24 * H, now_ms + 1_000)
    assert data.uptime_pct == {"okx": 75}

    episodes = EpisodeRepository(sessions)
    old = await _episode(episodes, opened=now_ms - 200 * 24 * H)
    await episodes.save([old.close(now_ms - 199 * 24 * H, EpisodeCloseReason.GAP)])
    await _episode(episodes, opened=now_ms - 200 * 24 * H, symbol="OPEN/USDT")  # still open
    counts = await RetentionRepository(sessions).purge(
        snapshots_before=now - timedelta(days=7),
        evaluations_before=now - timedelta(days=30),
        episodes_before=now - timedelta(days=90),
    )
    assert counts["opportunity_episodes"] == 1  # closed and old; the open one is kept
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OpportunityEpisodeRow)) == 1
