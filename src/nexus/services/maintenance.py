"""Housekeeping use case (runs in the ``maintenance`` worker)."""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from nexus.config.groups import MaintenanceSettings
from nexus.interfaces.repositories import IRetentionRepository

log = structlog.get_logger(__name__)


class RetentionService:
    """Applies the configured retention policy."""

    def __init__(
        self,
        repository: IRetentionRepository,
        settings: MaintenanceSettings,
        *,
        sending_stale_s: int | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._sending_stale_s = sending_stale_s

    async def purge(self, now: datetime) -> dict[str, int]:
        """Delete rows older than the retention windows; reap stale ``sending`` alert records."""
        counts = await self._repository.purge(
            snapshots_before=now - timedelta(days=self._settings.snapshot_retention_days),
            evaluations_before=now - timedelta(days=self._settings.evaluation_retention_days),
            episodes_before=now - timedelta(days=self._settings.episode_retention_days),
            alerts_sending_before=(
                now - timedelta(seconds=self._sending_stale_s)
                if self._sending_stale_s is not None
                else None
            ),
        )
        log.info("retention_purged", **counts)
        return counts
