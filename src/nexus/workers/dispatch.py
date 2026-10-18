"""Celery-backed alert dispatcher used by the scanner."""

from __future__ import annotations

import asyncio

from celery import Celery

from nexus.domain.events import SystemEvent, event_to_payload
from nexus.interfaces.coordination import IAlertDispatcher
from nexus.workers.app import ALERTS_QUEUE, TASK_SEND_EVENT, TASK_SEND_OPPORTUNITY

# Fail fast when the broker is down instead of blocking the scanner loop on publish retries.
_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.5,
    "interval_max": 1,
}


class CeleryAlertDispatcher(IAlertDispatcher):
    """Publishes alert tasks by name (the scanner never imports Telegram code or secrets)."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    async def dispatch_opportunity(self, evaluation_id: int) -> None:
        """Queue an opportunity alert for a stored evaluation."""
        await asyncio.to_thread(
            self._app.send_task,
            TASK_SEND_OPPORTUNITY,
            args=[evaluation_id],
            queue=ALERTS_QUEUE,
            retry=True,
            retry_policy=_PUBLISH_RETRY_POLICY,
        )

    async def dispatch_event(self, event: SystemEvent) -> None:
        """Queue a system event notification."""
        await asyncio.to_thread(
            self._app.send_task,
            TASK_SEND_EVENT,
            args=[event_to_payload(event)],
            queue=ALERTS_QUEUE,
            retry=True,
            retry_policy=_PUBLISH_RETRY_POLICY,
        )
