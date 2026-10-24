from pathlib import Path

from nexus.config.groups import CelerySettings, MaintenanceSettings, WatchdogSettings
from nexus.infra.backup_status import MAX_STATUS_BYTES, FileBackupStatus
from nexus.workers.app import TASK_WATCHDOG, create_celery_app


def test_watchdog_beat_entry_uses_the_configured_interval() -> None:
    app = create_celery_app(
        CelerySettings(),
        MaintenanceSettings(),
        watchdog_settings=WatchdogSettings(interval_s=120),
    )
    assert app.conf.beat_schedule["liveness-watchdog"] == {
        "task": TASK_WATCHDOG,
        "schedule": 120,
    }
    assert app.conf.task_routes["nexus.maintenance.*"] == {"queue": "maintenance"}


def test_watchdog_can_be_disabled() -> None:
    app = create_celery_app(
        CelerySettings(), MaintenanceSettings(), watchdog_settings=WatchdogSettings(enabled=False)
    )
    assert "liveness-watchdog" not in app.conf.beat_schedule


def test_watchdog_task_registered() -> None:
    from nexus.workers.app import celery_app

    assert TASK_WATCHDOG in set(celery_app.tasks)


async def test_status_file_reader(tmp_path: Path) -> None:
    path = tmp_path / "last_backup.json"
    reader = FileBackupStatus(str(path))
    assert await reader.read() is None
    path.write_text('{"ok": true}')
    assert await reader.read() == '{"ok": true}'
    path.write_text("x" * (MAX_STATUS_BYTES + 10))
    assert await reader.read() == "{}"


def test_backup_status_path_must_be_absolute() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WatchdogSettings(backup_status_path="last_backup.json")
