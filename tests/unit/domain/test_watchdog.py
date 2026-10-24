import json
from datetime import UTC, datetime

import pytest

from nexus.domain.watchdog import (
    BACKUP_FAILED,
    BACKUP_MISSING,
    BACKUP_NOT_COPIED,
    BACKUP_STALE,
    BACKUP_UNREADABLE,
    SCANNER_NO_DATA,
    SCANNER_STALE,
    check_backup,
    check_scanner,
)

NOW = int(datetime(2026, 10, 23, 12, 0, tzinfo=UTC).timestamp() * 1000)
MIN = 60_000


def _status(**overrides: object) -> str:
    data: dict[str, object] = {
        "finished_at": "2026-10-23T06:00:00Z",
        "ok": True,
        "dump": "nexus-20261023.dump",
        "copied": True,
    }
    return json.dumps({**data, **overrides})


def test_scanner_fresh_is_ok() -> None:
    assert check_scanner(NOW - 9 * MIN, NOW, 10).ok


def test_scanner_stale_reports_age() -> None:
    finding = check_scanner(NOW - 25 * MIN, NOW, 10)
    assert (finding.reason, finding.minutes) == (SCANNER_STALE, 25)
    assert not finding.needs_grace


def test_scanner_without_rows_needs_grace() -> None:
    finding = check_scanner(None, NOW, 10)
    assert finding.reason == SCANNER_NO_DATA
    assert finding.needs_grace


def test_scanner_future_timestamp_is_ok() -> None:
    assert check_scanner(NOW + 5 * MIN, NOW, 10).ok


def test_backup_healthy() -> None:
    assert check_backup(_status(), NOW, 26).ok


def test_backup_missing_needs_grace() -> None:
    finding = check_backup(None, NOW, 26)
    assert finding.reason == BACKUP_MISSING
    assert finding.needs_grace


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '{"finished_at": "yesterday", "ok": true, "copied": true}',
        _status(ok="yes"),
        _status(copied=1),
        _status(finished_at=None),
    ],
)
def test_backup_unreadable(raw: str) -> None:
    finding = check_backup(raw, NOW, 26)
    assert finding.reason == BACKUP_UNREADABLE
    assert finding.needs_grace


def test_backup_failed() -> None:
    finding = check_backup(_status(ok=False), NOW, 26)
    assert (finding.reason, finding.minutes) == (BACKUP_FAILED, 360)
    assert not finding.needs_grace


def test_backup_not_copied() -> None:
    assert check_backup(_status(copied=False), NOW, 26).reason == BACKUP_NOT_COPIED


def test_backup_older_than_limit_is_stale() -> None:
    old = _status(finished_at="2026-10-22T09:59:00Z")  # 26 h 1 min
    finding = check_backup(old, NOW, 26)
    assert (finding.reason, finding.minutes) == (BACKUP_STALE, 26 * 60 + 1)
    assert check_backup(_status(finished_at="2026-10-22T10:01:00Z"), NOW, 26).ok


def test_backup_naive_timestamp_is_utc() -> None:
    assert check_backup(_status(finished_at="2026-10-23T06:00:00"), NOW, 26).ok


def test_backup_future_finish_is_not_stale() -> None:
    assert check_backup(_status(finished_at="2026-10-23T13:00:00Z"), NOW, 26).ok
