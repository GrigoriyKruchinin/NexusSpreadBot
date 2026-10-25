"""Scanner-activity query with a faked session (SQL itself runs in integration tests)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from nexus.persistence.repositories import ScannerActivityRepository, datetime_to_ms

H0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


class _Session:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    async def scalar(self, _stmt: object) -> Any:
        return self._scalar


def _sessions(session: _Session) -> Any:
    @asynccontextmanager
    async def factory() -> Any:
        yield session

    return factory


async def test_last_activity_is_none_without_rows() -> None:
    assert await ScannerActivityRepository(_sessions(_Session(None))).last_activity_ms() is None


async def test_last_activity_converts_to_epoch_ms() -> None:
    repo = ScannerActivityRepository(_sessions(_Session(H0)))
    assert await repo.last_activity_ms() == datetime_to_ms(H0)
