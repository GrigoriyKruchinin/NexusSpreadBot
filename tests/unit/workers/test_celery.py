from contextlib import asynccontextmanager
from typing import Any, ClassVar

import pytest

from nexus.config.groups import CelerySettings, MaintenanceSettings
from nexus.domain.errors import NotificationError, NotificationRejectedError
from nexus.domain.events import AlertContext, ScannerStopped
from nexus.workers import tasks
from nexus.workers.app import (
    ALERTS_QUEUE,
    MAINTENANCE_QUEUE,
    TASK_PURGE,
    TASK_SEND_EVENT,
    TASK_SEND_OPPORTUNITY,
    create_celery_app,
)
from nexus.workers.dispatch import CeleryAlertDispatcher
from tests.fakes import ManualClock


def test_routing_and_beat_schedule() -> None:
    app = create_celery_app(CelerySettings(), MaintenanceSettings(cleanup_interval_s=900))
    routes = app.conf.task_routes
    assert routes["nexus.alerts.*"] == {"queue": ALERTS_QUEUE}
    assert routes["nexus.maintenance.*"] == {"queue": MAINTENANCE_QUEUE}
    assert app.conf.beat_schedule["purge-old-rows"] == {"task": TASK_PURGE, "schedule": 900}
    assert app.conf.task_acks_late is True


def test_tasks_registered() -> None:
    from nexus.workers.app import celery_app

    names = set(celery_app.tasks)
    assert {TASK_SEND_OPPORTUNITY, TASK_SEND_EVENT, TASK_PURGE} <= names


class _App:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[Any], str]] = []

    def send_task(self, name: str, args: list[Any], queue: str, **kwargs: Any) -> None:
        assert kwargs["retry_policy"]["max_retries"] <= 2
        self.sent.append((name, args, queue))


async def test_dispatcher_publishes_by_name() -> None:
    app = _App()
    dispatcher = CeleryAlertDispatcher(app, ManualClock(123))  # type: ignore[arg-type]
    await dispatcher.dispatch_opportunity(42)
    await dispatcher.dispatch_event(ScannerStopped(reason="test"))
    await dispatcher.dispatch_opportunity(43, AlertContext(7, 1, "8.5"))
    empty = {"volume": None, "transfer": None, "lifetime": None, "v": 2}
    no_context = {"episode_id": None, "realert": 0, "previous_net_usd": None, **empty}
    assert app.sent[0] == (TASK_SEND_OPPORTUNITY, [42, no_context], ALERTS_QUEUE)
    assert app.sent[2] == (
        TASK_SEND_OPPORTUNITY,
        [43, {"episode_id": 7, "realert": 1, "previous_net_usd": "8.5", **empty}],
        ALERTS_QUEUE,
    )
    assert app.sent[1] == (
        TASK_SEND_EVENT,
        [{"kind": "scanner_stopped", "data": {"reason": "test"}, "emitted_at_ms": 123}],
        ALERTS_QUEUE,
    )


class _Service:
    contexts: ClassVar[list[AlertContext]] = []

    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def send_opportunity(self, evaluation_id: int, context: AlertContext) -> Any:
        self.contexts.append(context)
        if self.error:
            raise self.error
        from nexus.services.alerts import AlertOutcome

        return AlertOutcome.SENT


def _patch_scope(monkeypatch: pytest.MonkeyPatch, error: Exception | None) -> None:
    @asynccontextmanager
    async def scope(_: object) -> Any:
        yield _Service(error)

    monkeypatch.setattr("nexus.container.alert_service_scope", scope)
    monkeypatch.setattr(tasks, "_alerts_settings", lambda: object())


def test_send_opportunity_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scope(monkeypatch, None)
    assert tasks.send_opportunity.apply(args=(1,)).get() == "sent"


def test_send_opportunity_task_passes_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scope(monkeypatch, None)
    _Service.contexts.clear()
    payload = {"episode_id": 3, "realert": 2, "previous_net_usd": "9"}
    assert tasks.send_opportunity.apply(args=(1, payload)).get() == "sent"
    assert tasks.send_opportunity.apply(args=(1,)).get() == "sent"  # tasks queued pre-1.5.5
    assert _Service.contexts == [AlertContext(3, 2, "9", v=1), AlertContext()]


def test_send_opportunity_task_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scope(monkeypatch, NotificationRejectedError("chat not found"))
    assert tasks.send_opportunity.apply(args=(1,)).get() == "rejected"


def test_send_opportunity_task_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_scope(monkeypatch, NotificationError("429", retry_after_s=3))
    retries: list[float] = []

    def fake_retry(*, exc: Exception, countdown: float) -> Exception:
        retries.append(countdown)
        return RuntimeError("retry scheduled")

    monkeypatch.setattr(tasks.send_opportunity, "retry", fake_retry)
    with pytest.raises(RuntimeError, match="retry scheduled"):
        tasks.send_opportunity.run(1)
    assert retries == [4.0]


def test_digest_beat_schedule_uses_local_time() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from nexus.config.groups import DigestSettings
    from nexus.workers.app import TASK_SEND_DIGEST, create_celery_app

    digest = DigestSettings(time="09:30", tz="Europe/Moscow")
    app = create_celery_app(CelerySettings(), MaintenanceSettings(), digest)
    entry = app.conf.beat_schedule["daily-digest"]
    assert (entry["task"], entry["args"]) == (TASK_SEND_DIGEST, ["Europe/Moscow"])
    schedule = entry["schedule"]
    assert schedule.hour == {9}
    assert schedule.minute == {30}
    assert schedule.nowfun().tzinfo == ZoneInfo("Europe/Moscow")
    assert isinstance(schedule.nowfun(), datetime)
    # Celery beat stores its schedule in a shelve (pickle): every entry must survive it.
    import pickle

    for name, item in app.conf.beat_schedule.items():
        restored = pickle.loads(pickle.dumps(item["schedule"]))  # noqa: S301 - own data
        assert repr(restored) == repr(item["schedule"]), name
    roundtrip = pickle.loads(pickle.dumps(schedule))  # noqa: S301 - own data
    assert roundtrip.nowfun().tzinfo == ZoneInfo("Europe/Moscow")
    disabled = create_celery_app(
        CelerySettings(), MaintenanceSettings(), DigestSettings(enabled=False)
    )
    assert "daily-digest" not in disabled.conf.beat_schedule


def test_send_digest_task(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Digest:
        async def send(self, tz: str) -> str:
            calls.append(tz)
            return "1"

    @asynccontextmanager
    async def scope(_: object) -> Any:
        yield _Digest()

    monkeypatch.setattr("nexus.container.digest_scope", scope)
    monkeypatch.setattr(tasks, "_alerts_settings", lambda: object())
    assert tasks.send_digest.apply(args=("UTC",)).get() == "sent"
    assert calls == ["UTC"]


def test_liveness_watchdog_task_runs_one_check(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dog:
        async def run_once(self) -> dict[str, str]:
            return {"scanner": "ok", "backup": "ok"}

    @asynccontextmanager
    async def scope(_: object) -> Any:
        yield _Dog()

    monkeypatch.setattr("nexus.container.watchdog_scope", scope)
    monkeypatch.setattr(tasks, "_maintenance_settings", lambda: object())
    assert tasks.liveness_watchdog.apply().get() == {"scanner": "ok", "backup": "ok"}
