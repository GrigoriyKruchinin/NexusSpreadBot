from datetime import UTC, datetime, timedelta

from nexus.config.groups import MaintenanceSettings
from nexus.services.maintenance import RetentionService
from tests.fakes import MemoryRepos


async def test_retention_windows() -> None:
    repos = MemoryRepos()
    now = datetime(2026, 10, 18, tzinfo=UTC)
    settings = MaintenanceSettings(snapshot_retention_days=7, evaluation_retention_days=30)
    await RetentionService(repos, settings).purge(now)
    assert repos.purged == [(now - timedelta(days=7), now - timedelta(days=30))]
