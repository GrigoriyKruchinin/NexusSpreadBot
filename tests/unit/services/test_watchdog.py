import json
from datetime import UTC, datetime

import pytest

from nexus.config.groups import WatchdogSettings
from nexus.domain.events import WatchdogAlert, WatchdogRecovered
from nexus.interfaces.watchdog import (
    IBackupStatusSource,
    IScannerActivity,
    IWatchdogState,
    WatchdogState,
)
from nexus.services.watchdog import LivenessWatchdog
from tests.fakes import ManualClock, RecordingDispatcher

MIN = 60_000
T0 = int(datetime(2026, 10, 23, 12, 0, tzinfo=UTC).timestamp() * 1000)


class Activity(IScannerActivity):
    def __init__(self) -> None:
        self.value: int | None = None
        self.error: Exception | None = None

    async def last_activity_ms(self) -> int | None:
        if self.error:
            raise self.error
        return self.value


class Backup(IBackupStatusSource):
    def __init__(self) -> None:
        self.raw: str | None = None

    async def read(self) -> str | None:
        return self.raw


class MemoryState(IWatchdogState):
    def __init__(self) -> None:
        self.items: dict[str, WatchdogState] = {}

    async def get(self, check: str) -> WatchdogState:
        return self.items.get(check, WatchdogState())

    async def save(self, check: str, state: WatchdogState) -> None:
        self.items[check] = state


class FailingDispatcher(RecordingDispatcher):
    fail = True

    async def dispatch_event(self, event: object) -> None:
        if self.fail:
            raise OSError("broker down")
        await super().dispatch_event(event)  # type: ignore[arg-type]


class Rig:
    def __init__(self, dispatcher: RecordingDispatcher | None = None) -> None:
        self.clock = ManualClock(T0)
        self.activity, self.backup, self.state = Activity(), Backup(), MemoryState()
        self.dispatcher = dispatcher or RecordingDispatcher()
        self.dog = LivenessWatchdog(
            activity=self.activity,
            backup=self.backup,
            state=self.state,
            dispatcher=self.dispatcher,
            clock=self.clock,
            settings=WatchdogSettings(scanner_stale_min=10, backup_max_age_h=26),
        )
        self.healthy()

    def healthy(self) -> None:
        self.activity.value = self.clock.now - MIN
        self.backup.raw = json.dumps(
            {
                "finished_at": datetime.fromtimestamp(self.clock.now / 1000, tz=UTC).isoformat(),
                "ok": True,
                "dump": "x.dump",
                "copied": True,
            }
        )

    def healthy_backup_only(self) -> None:
        self.backup.raw = json.dumps(
            {
                "finished_at": datetime.fromtimestamp(self.clock.now / 1000, tz=UTC).isoformat(),
                "ok": True,
                "dump": "x.dump",
                "copied": True,
            }
        )

    def advance(self, minutes: int) -> None:
        self.clock.now += minutes * MIN


async def test_all_healthy_sends_nothing() -> None:
    rig = Rig()
    assert await rig.dog.run_once() == {"scanner": "ok", "backup": "ok"}
    assert rig.dispatcher.events == []


async def test_stale_scanner_alerts_once_then_recovers_once() -> None:
    rig = Rig()
    rig.activity.value = T0 - 30 * MIN
    assert (await rig.dog.run_once())["scanner"] == "alert"
    for _ in range(3):
        rig.advance(5)
        assert (await rig.dog.run_once())["scanner"] == "firing"
    assert rig.dispatcher.events == [WatchdogAlert("scanner", "scanner_stale", 30)]
    rig.activity.value = rig.clock.now - MIN
    assert (await rig.dog.run_once())["scanner"] == "recovered"
    assert (await rig.dog.run_once())["scanner"] == "ok"
    recovered = rig.dispatcher.events[1]
    assert isinstance(recovered, WatchdogRecovered)
    assert recovered.check == "scanner"
    assert recovered.downtime_min == 45  # silent since 30 min before the first alert + 15 min
    assert len(rig.dispatcher.events) == 2


async def test_new_incident_after_recovery_alerts_again() -> None:
    rig = Rig()
    rig.activity.value = T0 - 20 * MIN
    await rig.dog.run_once()
    rig.activity.value = rig.clock.now
    await rig.dog.run_once()
    rig.advance(60)
    rig.activity.value = rig.clock.now - 15 * MIN
    await rig.dog.run_once()
    kinds = [type(e).__name__ for e in rig.dispatcher.events]
    assert kinds == ["WatchdogAlert", "WatchdogRecovered", "WatchdogAlert"]


async def test_scanner_without_rows_waits_for_the_grace_period() -> None:
    rig = Rig()
    rig.activity.value = None
    assert (await rig.dog.run_once())["scanner"] == "grace"
    rig.advance(5)
    assert (await rig.dog.run_once())["scanner"] == "grace"
    rig.advance(6)  # 11 min since first seen >= scanner_stale_min
    assert (await rig.dog.run_once())["scanner"] == "alert"
    assert rig.dispatcher.events == [WatchdogAlert("scanner", "scanner_no_data", None)]


async def test_blip_inside_grace_is_forgotten() -> None:
    rig = Rig()
    rig.activity.value = None
    await rig.dog.run_once()
    rig.advance(5)
    rig.activity.value = rig.clock.now
    assert (await rig.dog.run_once())["scanner"] == "ok"
    assert rig.state.items["scanner"] == WatchdogState()
    assert rig.dispatcher.events == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"ok": False}, "backup_failed"),
        ({"copied": False}, "backup_not_copied"),
    ],
)
async def test_backup_problems_alert_immediately(overrides: dict[str, bool], reason: str) -> None:
    rig = Rig()
    data = json.loads(rig.backup.raw or "")
    rig.backup.raw = json.dumps({**data, **overrides})
    assert (await rig.dog.run_once())["backup"] == "alert"
    assert isinstance(rig.dispatcher.events[0], WatchdogAlert)
    assert rig.dispatcher.events[0].reason == reason


async def test_old_backup_alerts_and_fresh_one_recovers() -> None:
    rig = Rig()
    rig.advance(27 * 60)
    rig.activity.value = rig.clock.now  # scanner stays healthy
    assert (await rig.dog.run_once())["backup"] == "alert"
    rig.healthy()
    assert (await rig.dog.run_once())["backup"] == "recovered"


async def test_missing_backup_file_alerts_after_the_max_age() -> None:
    rig = Rig()
    rig.backup.raw = None
    assert (await rig.dog.run_once())["backup"] == "grace"
    rig.advance(25 * 60)
    rig.activity.value = rig.clock.now
    assert (await rig.dog.run_once())["backup"] == "grace"
    rig.advance(2 * 60)
    rig.activity.value = rig.clock.now
    assert (await rig.dog.run_once())["backup"] == "alert"
    assert rig.dispatcher.events[0] == WatchdogAlert("backup", "backup_missing", None)


async def test_dispatch_failure_is_retried_next_run() -> None:
    dispatcher = FailingDispatcher()
    rig = Rig(dispatcher)
    rig.activity.value = T0 - 30 * MIN
    assert (await rig.dog.run_once())["scanner"] == "error"
    assert "scanner" not in rig.state.items  # nothing recorded: not deduplicated away
    dispatcher.fail = False
    assert (await rig.dog.run_once())["scanner"] == "alert"
    assert len(dispatcher.events) == 1


async def test_failing_check_does_not_skip_the_other() -> None:
    rig = Rig()
    rig.activity.error = RuntimeError("db down")
    data = json.loads(rig.backup.raw or "")
    rig.backup.raw = json.dumps({**data, "ok": False})
    actions = await rig.dog.run_once()
    assert actions == {"scanner": "error", "backup": "alert"}


async def test_persistent_check_error_alerts_once_after_the_grace_period() -> None:
    rig = Rig()
    rig.activity.error = RuntimeError("db down")
    assert (await rig.dog.run_once())["scanner"] == "error"
    assert rig.dispatcher.events == []
    rig.advance(5)
    await rig.dog.run_once()
    assert rig.dispatcher.events == []
    rig.advance(6)  # 11 min of errors >= scanner_stale_min
    rig.healthy_backup_only()
    await rig.dog.run_once()
    assert rig.dispatcher.events == [WatchdogAlert("scanner", "check_error", None)]
    for _ in range(3):
        rig.advance(5)
        rig.healthy_backup_only()
        await rig.dog.run_once()
    assert len(rig.dispatcher.events) == 1  # de-duplicated


async def test_check_error_recovery_is_announced_once() -> None:
    rig = Rig()
    rig.activity.error = RuntimeError("db down")
    await rig.dog.run_once()
    rig.advance(11)
    rig.healthy_backup_only()
    await rig.dog.run_once()
    rig.activity.error = None
    rig.activity.value = rig.clock.now - MIN
    assert (await rig.dog.run_once())["scanner"] == "recovered"
    assert (await rig.dog.run_once())["scanner"] == "ok"
    kinds = [type(e).__name__ for e in rig.dispatcher.events]
    assert kinds == ["WatchdogAlert", "WatchdogRecovered"]


async def test_short_error_burst_is_forgotten() -> None:
    rig = Rig()
    rig.activity.error = RuntimeError("db down")
    await rig.dog.run_once()
    rig.advance(3)
    rig.activity.error = None
    rig.activity.value = rig.clock.now
    assert (await rig.dog.run_once())["scanner"] == "ok"
    assert rig.state.items["scanner"] == WatchdogState()
    assert rig.dispatcher.events == []


async def test_unreadable_backup_file_error_alerts_after_grace() -> None:
    rig = Rig()

    async def broken() -> str | None:
        raise PermissionError("stale mount")

    rig.backup.read = broken  # type: ignore[method-assign]
    await rig.dog.run_once()
    rig.advance(26 * 60 + 1)
    rig.activity.value = rig.clock.now
    await rig.dog.run_once()
    assert rig.dispatcher.events == [WatchdogAlert("backup", "check_error", None)]


async def test_escalation_realerts_once_but_downgrade_does_not() -> None:
    rig = Rig()
    data = json.loads(rig.backup.raw or "")
    rig.backup.raw = json.dumps({**data, "copied": False})
    assert (await rig.dog.run_once())["backup"] == "alert"
    rig.advance(5)
    rig.activity.value = rig.clock.now
    assert (await rig.dog.run_once())["backup"] == "firing"
    rig.backup.raw = json.dumps({**data, "ok": False})
    assert (await rig.dog.run_once())["backup"] == "alert"
    assert (await rig.dog.run_once())["backup"] == "firing"
    rig.backup.raw = json.dumps({**data, "copied": False})  # milder again: stay quiet
    assert (await rig.dog.run_once())["backup"] == "firing"
    reasons = [e.reason for e in rig.dispatcher.events if isinstance(e, WatchdogAlert)]
    assert reasons == ["backup_not_copied", "backup_failed"]
    rig.healthy()
    assert (await rig.dog.run_once())["backup"] == "recovered"


async def test_alert_failure_while_check_is_broken_is_swallowed() -> None:
    rig = Rig()
    rig.activity.error = RuntimeError("db down")

    async def broken_save(check: str, state: WatchdogState) -> None:
        raise OSError("redis down")

    rig.state.save = broken_save  # type: ignore[method-assign]
    actions = await rig.dog.run_once()
    assert actions["scanner"] == "error"
    assert rig.dispatcher.events == []
