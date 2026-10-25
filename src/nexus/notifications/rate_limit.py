"""Client-side Telegram rate limiting: a small sliding-window limiter shared by the process."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from functools import cache

from nexus.domain.errors import NotificationError

DEFAULT_MAX_WAIT_S = 20.0
"""Longest a task sleeps for a slot; a longer wait is handed back to the task retry instead."""


class SendRateLimiter:
    """Allows at most one call per ``min_interval_s`` and ``max_per_minute`` calls per 60 s.

    Slots are reserved under a thread lock (each Celery task runs its own event loop), then the
    caller sleeps until its slot. A Telegram 429 pushes every later slot behind ``retry_after``
    (:meth:`block_for`). State is per process: run the alerts worker with ``--concurrency 1``.
    """

    def __init__(
        self,
        *,
        min_interval_s: float = 1.0,
        max_per_minute: int = 20,
        max_wait_s: float = DEFAULT_MAX_WAIT_S,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min_interval = min_interval_s
        self._max_per_minute = max_per_minute
        self._max_wait = max_wait_s
        self._now = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._slots: deque[float] = deque()
        """Reserved call times (monotonic seconds), oldest first."""
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        """No call before ``seconds`` from now (a 429 ``retry_after``)."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._now() + seconds)

    def _reserve(self) -> float:
        """Reserve the next slot; returns how long to wait for it."""
        with self._lock:
            now = self._now()
            while self._slots and self._slots[0] <= now - 60:
                self._slots.popleft()
            start = max(now, self._blocked_until)
            if self._slots:
                start = max(start, self._slots[-1] + self._min_interval)
            if len(self._slots) >= self._max_per_minute:
                start = max(start, self._slots[-self._max_per_minute] + 60)
            wait = start - now
            if wait > self._max_wait:
                raise NotificationError(
                    f"local telegram rate limit: next slot in {wait:.0f} s",
                    retry_after_s=wait,
                )
            self._slots.append(start)
            return wait

    async def acquire(self) -> None:
        """Wait for a slot; raises :class:`NotificationError` if it is too far away."""
        wait = self._reserve()
        if wait > 0:
            await self._sleep(wait)


@cache
def process_limiter(min_interval_s: float, max_per_minute: int) -> SendRateLimiter:
    """The limiter shared by every notifier of this process (tasks create notifiers per run)."""
    return SendRateLimiter(min_interval_s=min_interval_s, max_per_minute=max_per_minute)
