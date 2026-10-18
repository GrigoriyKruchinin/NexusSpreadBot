import pytest

from nexus.domain.errors import NotificationError
from nexus.domain.events import ExchangeRecovered, event_to_payload
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
    assert "Arbitrage Opportunity" in notifier.sent[0].text
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
    status, error = repos.alerts[evaluation_id]
    assert status is AlertDeliveryStatus.FAILED
    assert error is not None
    assert "expired" in error


async def test_delivery_failure_recorded_and_reraised() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier(error=NotificationError("429"))
    [evaluation_id] = await repos.add_evaluations([make_evaluation()])
    with pytest.raises(NotificationError):
        await _service(repos, notifier).send_opportunity(evaluation_id)
    assert repos.alerts[evaluation_id][0] is AlertDeliveryStatus.FAILED


async def test_system_event_recovered_is_silent() -> None:
    repos, notifier = MemoryRepos(), RecordingNotifier()
    payload = event_to_payload(ExchangeRecovered(exchange="okx", downtime_s=12))
    assert await _service(repos, notifier).send_event(payload) is AlertOutcome.SENT
    assert notifier.sent[0].silent
    assert "OKX recovered" in notifier.sent[0].text
