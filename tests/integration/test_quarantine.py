import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.persistence.models import RouteQuarantineRow
from nexus.persistence.repositories import QuarantineRepository, ms_to_datetime

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
HOUR = 3_600_000


def _quarantine(start: int) -> RouteQuarantine:
    return RouteQuarantine(
        symbol="ONE/USDT",
        buy_exchange="okx",
        sell_exchange="binance",
        reason=QuarantineReason.TRANSFER_UNAVAILABLE,
        started_at_ms=start,
        expires_at_ms=start + 24 * HOUR,
        note="deposits disabled on binance",
    )


async def test_quarantine_history_start_and_early_lift(sessions: Sessions) -> None:
    repo = QuarantineRepository(sessions)
    await repo.record_start(_quarantine(T0 - 48 * HOUR))  # an old, expired quarantine
    await repo.record_start(_quarantine(T0))
    await repo.record_lift("ONE/USDT|okx>binance", T0 + HOUR)
    await repo.record_lift("OTHER/USDT|okx>binance", T0 + HOUR)  # no-op
    async with sessions() as session:
        rows = (
            await session.scalars(select(RouteQuarantineRow).order_by(RouteQuarantineRow.id))
        ).all()
    assert [r.lifted_at for r in rows] == [None, ms_to_datetime(T0 + HOUR)]
    assert rows[1].reason == "transfer_unavailable"
    assert rows[1].note == "deposits disabled on binance"
