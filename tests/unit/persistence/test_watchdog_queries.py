"""Watchdog / coverage queries with a faked session (SQL itself runs in integration tests)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from nexus.persistence.repositories import (
    DigestRepository,
    ScannerActivityRepository,
    datetime_to_ms,
)

H0 = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
HOUR = 3_600_000


class _Session:
    def __init__(self, scalar: Any = None, results: list[list[tuple[Any, ...]]] | None = None):
        self._scalar = scalar
        self._results = results or []

    async def scalar(self, _stmt: object) -> Any:
        return self._scalar

    async def execute(self, _stmt: object) -> Any:
        rows = self._results.pop(0)
        return SimpleNamespace(all=lambda: rows)


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


async def test_set_coverage_from_hourly_sweeps() -> None:
    since = datetime_to_ms(H0)
    first = datetime_to_ms(H0) - 24 * HOUR
    hours = [(datetime_to_ms(H0) + h * HOUR) for h in range(4)]
    stats = [
        ("all", datetime.fromtimestamp(ms / 1000, tz=UTC), 360 if i != 2 else 0)
        for i, ms in enumerate(hours)
    ]
    first_rows = [("all", datetime.fromtimestamp(first / 1000, tz=UTC))]
    session: Any = _Session(results=[first_rows, stats])
    repo = DigestRepository(_sessions(session), coverage_min_sweeps_per_hour=60)
    (cov,) = await repo._set_coverage(session, since, since + 4 * HOUR)
    assert (cov.portfolio_id, cov.hours_expected, cov.hours_gap, cov.downtime_min) == (
        "all",
        4,
        1,
        60,
    )
