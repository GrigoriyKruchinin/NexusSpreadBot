"""Celery tasks: thin adapters running async use cases with ``asyncio.run``.

Settings are loaded lazily per worker role, so the ``alerts`` worker only needs Telegram +
database variables and the ``maintenance`` worker only database variables.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from functools import cache
from typing import Any

import structlog
from celery import Task
from celery.signals import worker_init, worker_process_init
from sqlalchemy.exc import SQLAlchemyError

from nexus.config.groups import LoggingSettings
from nexus.config.roles import AlertsWorkerSettings, MaintenanceWorkerSettings
from nexus.domain.errors import NotificationError, NotificationRejectedError
from nexus.domain.events import AlertContext
from nexus.log import configure_logging
from nexus.workers.app import TASK_PURGE, TASK_SEND_EVENT, TASK_SEND_OPPORTUNITY, celery_app

log = structlog.get_logger(__name__)

MAX_RETRIES = 5
# Infrastructure hiccups (DB / network) are retried with backoff instead of losing the alert;
# AlertService expiry still bounds how stale a retried alert can be.
_INFRA_ERRORS = (SQLAlchemyError, OSError)
_INFRA_RETRY: dict[str, Any] = {
    "autoretry_for": _INFRA_ERRORS,
    "retry_backoff": 5,
    "retry_backoff_max": 60,
    "retry_jitter": True,
}


WORKER_ROLE_ENV = "NEXUS_WORKER_ROLE"


@worker_init.connect
def _validate_role_settings(**_: Any) -> None:
    """Fail fast at worker start if the role's settings are incomplete."""
    role = os.environ.get(WORKER_ROLE_ENV, "")
    if role == "alerts":
        _alerts_settings()
    elif role == "maintenance":
        _maintenance_settings()


@worker_process_init.connect
def _init_logging(**_: Any) -> None:
    role = os.environ.get(WORKER_ROLE_ENV, "worker")
    configure_logging(LoggingSettings(), service=f"worker-{role}")


@cache
def _alerts_settings() -> AlertsWorkerSettings:
    return AlertsWorkerSettings.load()


@cache
def _maintenance_settings() -> MaintenanceWorkerSettings:
    return MaintenanceWorkerSettings.load()


def _retry_countdown(task: Task[Any, Any], exc: NotificationError) -> float:
    if exc.retry_after_s is not None:
        return exc.retry_after_s + 1
    return float(min(300, 5 * 2**task.request.retries))


@celery_app.task(name=TASK_SEND_OPPORTUNITY, bind=True, max_retries=MAX_RETRIES, **_INFRA_RETRY)
def send_opportunity(
    self: Task[Any, Any], evaluation_id: int, context: dict[str, Any] | None = None
) -> str:
    """Deliver an opportunity alert (``context``: :class:`AlertContext` payload, optional)."""
    from nexus.container import alert_service_scope

    async def run() -> str:
        async with alert_service_scope(_alerts_settings()) as service:
            outcome = await service.send_opportunity(
                evaluation_id, AlertContext.from_payload(context)
            )
            return outcome.value

    try:
        return asyncio.run(run())
    except NotificationRejectedError as exc:
        log.error("alert_rejected", evaluation_id=evaluation_id, error=str(exc))
        return "rejected"
    except NotificationError as exc:
        raise self.retry(exc=exc, countdown=_retry_countdown(self, exc)) from None


@celery_app.task(name=TASK_SEND_EVENT, bind=True, max_retries=MAX_RETRIES, **_INFRA_RETRY)
def send_event(self: Task[Any, Any], payload: dict[str, Any]) -> str:
    """Deliver a system event notification."""
    from nexus.container import alert_service_scope

    async def run() -> str:
        async with alert_service_scope(_alerts_settings()) as service:
            return (await service.send_event(payload)).value

    try:
        return asyncio.run(run())
    except NotificationRejectedError as exc:
        log.error("event_rejected", kind=payload.get("kind"), error=str(exc))
        return "rejected"
    except NotificationError as exc:
        raise self.retry(exc=exc, countdown=_retry_countdown(self, exc)) from None


@celery_app.task(name=TASK_PURGE, max_retries=3, **_INFRA_RETRY)
def purge_old_rows() -> dict[str, int]:
    """Apply the retention policy."""
    from nexus.container import retention_scope

    async def run() -> dict[str, int]:
        async with retention_scope(_maintenance_settings()) as service:
            return await service.purge(datetime.now(tz=UTC))

    return asyncio.run(run())
