"""Celery application (broker settings only; no secrets beyond the broker URL).

Workers: ``celery -A nexus.workers.app:celery_app worker -Q alerts`` (or ``maintenance``).
Beat:    ``celery -A nexus.workers.app:celery_app beat``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

from nexus.config.groups import CelerySettings, DigestSettings, MaintenanceSettings

ALERTS_QUEUE = "alerts"
MAINTENANCE_QUEUE = "maintenance"

TASK_SEND_OPPORTUNITY = "nexus.alerts.send_opportunity"
TASK_SEND_EVENT = "nexus.alerts.send_event"
TASK_PURGE = "nexus.maintenance.purge"
TASK_SEND_DIGEST = "nexus.alerts.send_digest"


class LocalNow:
    """Picklable ``nowfun`` for crontab: beat persists its schedule with ``shelve``."""

    def __init__(self, tz: str) -> None:
        self.tz = tz

    def __call__(self) -> datetime:
        """Current time in :attr:`tz`."""
        return datetime.now(tz=ZoneInfo(self.tz))


def digest_schedule(digest: DigestSettings) -> dict[str, Any]:
    """Beat entry sending the digest daily at ``DIGEST_TIME`` in ``DIGEST_TZ``.

    ``Any``: Celery beat entries are untyped dicts.
    """
    return {
        "task": TASK_SEND_DIGEST,
        "schedule": crontab(minute=digest.minute, hour=digest.hour, nowfun=LocalNow(digest.tz)),
        "args": [digest.tz],
    }


def create_celery_app(
    celery_settings: CelerySettings | None = None,
    maintenance_settings: MaintenanceSettings | None = None,
    digest_settings: DigestSettings | None = None,
) -> Celery:
    """Build the Celery app with routing and the beat schedule."""
    settings = celery_settings or CelerySettings()
    maintenance = maintenance_settings or MaintenanceSettings()
    digest = digest_settings or DigestSettings()
    schedule: dict[str, Any] = {
        "purge-old-rows": {"task": TASK_PURGE, "schedule": maintenance.cleanup_interval_s},
    }
    if digest.enabled:
        schedule["daily-digest"] = digest_schedule(digest)
    app = Celery("nexus", broker=settings.broker_url.get_secret_value())
    app.conf.update(
        task_routes={
            "nexus.alerts.*": {"queue": ALERTS_QUEUE},
            "nexus.maintenance.*": {"queue": MAINTENANCE_QUEUE},
        },
        task_default_queue=ALERTS_QUEUE,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_ignore_result=True,
        worker_prefetch_multiplier=1,
        worker_hijack_root_logger=False,
        broker_connection_retry_on_startup=True,
        timezone=settings.timezone,
        enable_utc=True,
        beat_schedule=schedule,
        include=["nexus.workers.tasks"],
    )
    return app


celery_app = create_celery_app()
