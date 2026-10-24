"""Liveness checks as pure functions (scanner activity, backup status file).

The reasons are codes; the notifier turns them into Russian text. Nothing here reads files, the
clock or the network: inputs are passed in, so every branch is unit-testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

CHECK_SCANNER: Final = "scanner"
CHECK_BACKUP: Final = "backup"
CHECKS: Final = (CHECK_SCANNER, CHECK_BACKUP)

SCANNER_STALE: Final = "scanner_stale"
SCANNER_NO_DATA: Final = "scanner_no_data"
BACKUP_MISSING: Final = "backup_missing"
BACKUP_UNREADABLE: Final = "backup_unreadable"
BACKUP_FAILED: Final = "backup_failed"
BACKUP_NOT_COPIED: Final = "backup_not_copied"
BACKUP_STALE: Final = "backup_stale"
CHECK_ERROR: Final = "check_error"

#: Reasons that can be a normal state right after a fresh start (no data / no backup yet):
#: they alert only after persisting for the check's grace period.
GRACE_REASONS: Final = frozenset({SCANNER_NO_DATA, BACKUP_MISSING, BACKUP_UNREADABLE, CHECK_ERROR})

#: Severity rank: a firing incident is announced again when its reason ranks higher.
SEVERITY: Final[dict[str, int]] = {
    SCANNER_NO_DATA: 1,
    BACKUP_MISSING: 1,
    BACKUP_UNREADABLE: 1,
    CHECK_ERROR: 1,
    BACKUP_NOT_COPIED: 2,
    SCANNER_STALE: 3,
    BACKUP_STALE: 3,
    BACKUP_FAILED: 3,
}

MINUTE_MS: Final = 60_000
HOUR_MS: Final = 3_600_000


@dataclass(frozen=True, slots=True)
class Finding:
    """Outcome of one check; ``reason is None`` means healthy."""

    check: str
    reason: str | None = None
    minutes: int | None = None

    @property
    def ok(self) -> bool:
        """True when the check passed."""
        return self.reason is None

    @property
    def needs_grace(self) -> bool:
        """The reason may be a normal fresh-start state: alert only if it persists."""
        return self.reason in GRACE_REASONS


def check_scanner(last_activity_ms: int | None, now_ms: int, stale_min: int) -> Finding:
    """The scanner records exchange calls every sweep; silence means it is not sweeping."""
    if last_activity_ms is None:
        return Finding(CHECK_SCANNER, SCANNER_NO_DATA)
    age_min = max(0, (now_ms - last_activity_ms) // MINUTE_MS)
    if age_min >= stale_min:
        return Finding(CHECK_SCANNER, SCANNER_STALE, age_min)
    return Finding(CHECK_SCANNER)


def check_backup(raw: str | None, now_ms: int, max_age_h: int) -> Finding:
    """Validate the status file written by ``scripts/backup.sh`` (contract: devops S0a).

    ``raw`` is the file text, ``None`` when the file does not exist.
    """
    if raw is None:
        return Finding(CHECK_BACKUP, BACKUP_MISSING)
    try:
        data = json.loads(raw)
        finished = datetime.fromisoformat(str(data["finished_at"]))
        ok, copied = data["ok"], data["copied"]
    except (ValueError, KeyError, TypeError):
        return Finding(CHECK_BACKUP, BACKUP_UNREADABLE)
    if not isinstance(ok, bool) or not isinstance(copied, bool):
        return Finding(CHECK_BACKUP, BACKUP_UNREADABLE)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    age_min = max(0, (now_ms - int(finished.timestamp() * 1000)) // MINUTE_MS)
    if not ok:
        return Finding(CHECK_BACKUP, BACKUP_FAILED, age_min)
    if age_min >= max_age_h * 60:
        return Finding(CHECK_BACKUP, BACKUP_STALE, age_min)
    if not copied:
        return Finding(CHECK_BACKUP, BACKUP_NOT_COPIED, age_min)
    return Finding(CHECK_BACKUP)
