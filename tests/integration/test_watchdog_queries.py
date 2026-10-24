from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.interfaces.repositories import CapStatsDelta
from nexus.persistence.repositories import (
    DigestRepository,
    ExchangeHealthRepository,
    PaperRepository,
    ScannerActivityRepository,
)

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
H = 3_600_000
T0 = 1_800_000_000_000 // H * H


async def test_last_activity_tracks_the_newest_health_row(sessions: Sessions) -> None:
    repo = ScannerActivityRepository(sessions)
    assert await repo.last_activity_ms() is None
    before = int(datetime.now(tz=UTC).timestamp() * 1000)
    await ExchangeHealthRepository(sessions).record("okx", "fetch_tickers", ok=True, latency_ms=5)
    last = await repo.last_activity_ms()
    assert last is not None
    assert before - 1_000 <= last <= before + 60_000


async def test_digest_reports_set_coverage_from_cap_stats(sessions: Sessions) -> None:
    paper = PaperRepository(sessions)
    await paper.add_cap_stats(
        [CapStatsDelta("all", T0 - 2 * H + h * H, sweeps=360) for h in range(26) if h != 5]
    )
    data = await DigestRepository(sessions, coverage_min_sweeps_per_hour=60).collect(
        T0, T0 + 24 * H + 600_000
    )
    (cov,) = data.coverage
    assert cov.portfolio_id == "all"
    assert cov.hours_expected == 24
    assert (cov.hours_gap, cov.downtime_min) == (1, 60)
