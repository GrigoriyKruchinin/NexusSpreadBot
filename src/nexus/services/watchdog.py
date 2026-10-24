"""Liveness watchdog use case (runs in the ``maintenance`` worker, period from config).

Each run evaluates the scanner and the backup status. A problem raises exactly one alert per
incident and, once healthy again, exactly one recovery message. Incident state lives in Redis,
so a worker restart neither repeats an alert nor loses a pending recovery. State is saved only
after the message was queued: a failed dispatch is retried on the next run.
"""

from __future__ import annotations

import structlog

from nexus.config.groups import WatchdogSettings
from nexus.domain.clock import Clock
from nexus.domain.events import WatchdogAlert, WatchdogRecovered
from nexus.domain.watchdog import (
    CHECK_BACKUP,
    CHECK_SCANNER,
    MINUTE_MS,
    SCANNER_STALE,
    Finding,
    check_backup,
    check_scanner,
)
from nexus.interfaces.coordination import IAlertDispatcher
from nexus.interfaces.watchdog import (
    IBackupStatusSource,
    IScannerActivity,
    IWatchdogState,
    WatchdogState,
)

log = structlog.get_logger(__name__)


class LivenessWatchdog:
    """Turns check findings into de-duplicated alert / recovery events."""

    def __init__(
        self,
        *,
        activity: IScannerActivity,
        backup: IBackupStatusSource,
        state: IWatchdogState,
        dispatcher: IAlertDispatcher,
        clock: Clock,
        settings: WatchdogSettings,
    ) -> None:
        self._activity = activity
        self._backup = backup
        self._state = state
        self._dispatcher = dispatcher
        self._clock = clock
        self._settings = settings

    async def run_once(self) -> dict[str, str]:
        """Evaluate both checks; returns ``{check: action}`` (``alert``/``recovered``/...).

        A failure inside one check (database, Redis, broker) is logged and does not skip the
        other check.
        """
        now = self._clock.now_ms()
        actions: dict[str, str] = {}
        for check, probe in (
            (CHECK_SCANNER, self._probe_scanner),
            (CHECK_BACKUP, self._probe_backup),
        ):
            try:
                actions[check] = await self._apply(await probe(now), now)
            except Exception as error:
                log.error("watchdog_check_failed", check=check, error=type(error).__name__)
                actions[check] = "error"
        return actions

    async def _probe_scanner(self, now_ms: int) -> Finding:
        return check_scanner(
            await self._activity.last_activity_ms(), now_ms, self._settings.scanner_stale_min
        )

    async def _probe_backup(self, now_ms: int) -> Finding:
        return check_backup(await self._backup.read(), now_ms, self._settings.backup_max_age_h)

    def _grace_ms(self, check: str) -> int:
        if check == CHECK_SCANNER:
            return self._settings.scanner_stale_min * MINUTE_MS
        return self._settings.backup_max_age_h * 60 * MINUTE_MS

    async def _apply(self, finding: Finding, now_ms: int) -> str:
        state = await self._state.get(finding.check)
        if finding.ok:
            return await self._healthy(finding.check, state, now_ms)
        since = state.since_ms
        if since is None:
            # A stale scanner has been silent since its last call, not since we noticed.
            silent = finding.minutes if finding.reason == SCANNER_STALE else 0
            since = now_ms - (silent or 0) * MINUTE_MS
        if state.firing:
            return "firing"  # already announced: one alert per incident
        if finding.needs_grace and now_ms - since < self._grace_ms(finding.check):
            await self._state.save(finding.check, WatchdogState(False, since, finding.reason))
            return "grace"
        await self._dispatcher.dispatch_event(
            WatchdogAlert(finding.check, finding.reason or "", finding.minutes)
        )
        await self._state.save(finding.check, WatchdogState(True, since, finding.reason))
        log.warning("watchdog_alert", check=finding.check, reason=finding.reason)
        return "alert"

    async def _healthy(self, check: str, state: WatchdogState, now_ms: int) -> str:
        if not state.firing:
            if state.since_ms is not None:  # a short blip inside the grace period: forget it
                await self._state.save(check, WatchdogState())
            return "ok"
        since = state.since_ms if state.since_ms is not None else now_ms
        await self._dispatcher.dispatch_event(
            WatchdogRecovered(check, max(0, (now_ms - since) // MINUTE_MS))
        )
        await self._state.save(check, WatchdogState())
        log.info("watchdog_recovered", check=check)
        return "recovered"
