from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.persistence.repositories import (
    ExchangeHealthRepository,
    ScannerActivityRepository,
)

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]


async def test_last_activity_tracks_the_newest_health_row(sessions: Sessions) -> None:
    repo = ScannerActivityRepository(sessions)
    assert await repo.last_activity_ms() is None
    before = int(datetime.now(tz=UTC).timestamp() * 1000)
    await ExchangeHealthRepository(sessions).record("okx", "fetch_tickers", ok=True, latency_ms=5)
    last = await repo.last_activity_ms()
    assert last is not None
    assert before - 1_000 <= last <= before + 60_000
