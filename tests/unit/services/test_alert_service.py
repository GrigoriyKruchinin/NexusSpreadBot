import pytest

from nexus.domain.errors import NotificationError
from nexus.domain.events import (
    AlertContext,
    EpisodeClosed,
    ExchangeRecovered,
    WatchdogAlert,
    WatchdogRecovered,
    event_to_payload,
)
from nexus.domain.spread import EvaluationStatus
from nexus.interfaces.repositories import AlertDeliveryStatus
from nexus.services.alerts import AlertOutcome, AlertService
from tests.fakes import ManualClock, MemoryRepos, RecordingNotifier
from tests.support import EVALUATED_AT_MS, make_evaluation


def _service(
    repos: MemoryRepos, notifier: RecordingNotifier, now: int = EVALUATED_AT_MS + 5_000
) -> AlertService:
    return AlertService(
        evaluations=repos, alert_log=repos, notifier=notifier, clock=ManualClock(now), max_age_s=120
    )


async def test_sends_once_and_records() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    service = _service(repos, notifier)
    assert await service.send_opportunity(evaluation_id) is AlertOutcome.SENT
    assert repos.alerts[evaluation_id][0] is AlertDeliveryStatus.SENT
    assert "<b>ABC</b>/USDT" in notifier.sent[0].text
    assert await service.send_opportunity(evaluation_id) is AlertOutcome.DUPLICATE
    assert len(notifier.sent) == 1


async def test_missing_and_not_alertable() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    [stale] = await repos.add_evaluations(
        [make_evaluation(status=EvaluationStatus.STALE_BOOK, with_breakdown=False)]
    )
    service = _service(repos, notifier)
    assert await service.send_opportunity(999) is AlertOutcome.MISSING
    assert await service.send_opportunity(stale) is AlertOutcome.NOT_ALERTABLE
    assert notifier.sent == []


async def test_expired_alert_dropped() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    service = _service(repos, notifier, now=EVALUATED_AT_MS + 121_000)
    assert await service.send_opportunity(evaluation_id) is AlertOutcome.EXPIRED
    assert notifier.sent == []
    assert evaluation_id not in repos.alerts


async def test_delivery_failure_recorded_and_reraised() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier(error=NotificationError("429"))
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    with pytest.raises(NotificationError):
        await _service(repos, notifier).send_opportunity(evaluation_id)
    assert repos.alerts[evaluation_id][0] is AlertDeliveryStatus.FAILED
    # The failed attempt releases the claim: a Celery retry may deliver it.
    notifier.error = None
    assert await _service(repos, notifier).send_opportunity(evaluation_id) is AlertOutcome.SENT
    assert len(notifier.sent) == 1


async def test_claimed_alert_not_resent_after_redelivery() -> None:
    """A worker died after claiming (row left SENDING): redelivery must not send again."""
    repos, notifier = MemoryRepos(), RecordingNotifier()
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    assert await repos.claim(evaluation_id, channel="telegram")
    assert await _service(repos, notifier).send_opportunity(evaluation_id) is (
        AlertOutcome.DUPLICATE
    )
    assert notifier.sent == []


async def test_unexpected_send_error_releases_claim() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier(error=RuntimeError("boom"))
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    with pytest.raises(RuntimeError):
        await _service(repos, notifier).send_opportunity(evaluation_id)
    assert repos.alerts[evaluation_id] == (AlertDeliveryStatus.FAILED, "boom")


async def test_system_event_recovered_is_silent() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    payload = event_to_payload(ExchangeRecovered(exchange="okx", downtime_s=12))
    assert await _service(repos, notifier).send_event(payload) is AlertOutcome.SENT
    assert notifier.sent[0].silent
    assert "OKX is available again" in notifier.sent[0].text


async def test_stale_system_event_dropped() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    now = EVALUATED_AT_MS
    service = AlertService(
        evaluations=repos,
        alert_log=repos,
        notifier=notifier,
        clock=ManualClock(now),
        max_age_s=30,
        event_max_age_s=300,
    )
    event = ExchangeRecovered(exchange="okx", downtime_s=12)
    stale = event_to_payload(event, emitted_at_ms=now - 301_000)
    fresh = event_to_payload(event, emitted_at_ms=now - 299_000)
    assert await service.send_event(stale) is AlertOutcome.EXPIRED
    assert notifier.sent == []
    assert await service.send_event(fresh) is AlertOutcome.SENT
    assert len(notifier.sent) == 1


async def test_watchdog_events_never_expire() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    now = EVALUATED_AT_MS
    service = AlertService(
        evaluations=repos,
        alert_log=repos,
        notifier=notifier,
        clock=ManualClock(now),
        max_age_s=30,
        event_max_age_s=300,
    )
    old = now - 6 * 3_600_000  # an alerts-worker outage of hours
    alert = event_to_payload(WatchdogAlert("scanner", "scanner_stale", 40), emitted_at_ms=old)
    back = event_to_payload(WatchdogRecovered("scanner", 50), emitted_at_ms=old)
    assert await service.send_event(alert) is AlertOutcome.SENT
    assert await service.send_event(back) is AlertOutcome.SENT
    assert len(notifier.sent) == 2


async def test_realert_context_reaches_the_message() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    context = AlertContext(episode_id=9, realert=1, previous_net_usd="5")
    assert await _service(repos, notifier).send_opportunity(evaluation_id, context) is (
        AlertOutcome.SENT
    )
    assert "🔄" in notifier.sent[0].text
    assert "#9" in notifier.sent[0].text


async def test_episode_closed_is_silent() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    event = EpisodeClosed("ABC/USDT", "a", "b", "gap", 90, "7", "0.7", 5, 0, None)
    payload = event_to_payload(event, emitted_at_ms=EVALUATED_AT_MS + 5_000)
    assert await _service(repos, notifier).send_event(payload) is AlertOutcome.SENT
    assert notifier.sent[0].silent
    assert "Opportunity closed" in notifier.sent[0].text
