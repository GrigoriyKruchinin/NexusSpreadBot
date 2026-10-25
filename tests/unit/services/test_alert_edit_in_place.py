"""T5: one episode = one Telegram message (NEW sends, UPDATE edits, CLOSED edits)."""

from decimal import Decimal as D

import pytest

from nexus.domain.errors import MessageGoneError, NotificationError
from nexus.domain.events import AlertContext, AlertLifetime, EpisodeClosed, event_to_payload
from nexus.interfaces.repositories import AlertDeliveryStatus
from nexus.services.alerts import HOUR_MS, AlertOutcome, AlertService
from tests.fakes import ManualClock, MemoryAlertMessages, MemoryRepos, RecordingNotifier
from tests.support import EVALUATED_AT_MS, make_evaluation

NOW = EVALUATED_AT_MS + 5_000


class Rig:
    def __init__(self, *, max_per_hour: int = 30) -> None:
        self.repos = MemoryRepos()
        self.messages = MemoryAlertMessages()
        self.notifier = RecordingNotifier()
        self.clock = ManualClock(NOW)
        self.service = AlertService(
            evaluations=self.repos,
            alert_log=self.repos,
            notifier=self.notifier,
            clock=self.clock,
            max_age_s=120,
            messages=self.messages,
            max_per_hour=max_per_hour,
        )

    async def evaluation(self, net: str = "8", symbol: str = "ABC/USDT") -> int:
        [evaluation_id] = await self.repos.add_evaluations(
            [make_evaluation(net_usd=D(net), symbol=symbol, evaluated_at_ms=NOW - 1_000)]
        )
        return evaluation_id


def _context(realert: int = 0, episode_id: int = 7) -> AlertContext:
    return AlertContext(
        episode_id=episode_id,
        realert=realert,
        lifetime=AlertLifetime(NOW - 60_000, NOW - 1_000),
    )


async def test_new_update_close_is_one_send_and_edits() -> None:
    rig = Rig()
    first = await rig.evaluation("8")
    assert await rig.service.send_opportunity(first, _context()) is AlertOutcome.SENT
    second = await rig.evaluation("12")
    assert await rig.service.send_opportunity(second, _context(1)) is AlertOutcome.SENT
    third = await rig.evaluation("18")
    assert await rig.service.send_opportunity(third, _context(2)) is AlertOutcome.SENT

    assert len(rig.notifier.sent) == 1  # a single message for the whole episode
    assert [message_id for message_id, _ in rig.notifier.edits] == ["1", "1"]
    assert "🟢" in rig.notifier.sent[0].text
    assert all("🔄" in message.text for _, message in rig.notifier.edits)
    stored = rig.messages.episodes[7]
    assert (stored.message_id, stored.evaluation_id) == ("1", third)  # latest rendering kept

    closed = EpisodeClosed(
        "ABC/USDT", "binance", "kucoin", "gap", 150, "18", "1.8", 4, 2, True,
        episode_id=7, opened_at_ms=NOW - 150_000, last_seen_at_ms=NOW, closed_at_ms=NOW + 300_000,
    )  # fmt: skip
    payload = event_to_payload(closed, emitted_at_ms=NOW)
    assert await rig.service.send_event(payload) is AlertOutcome.SENT
    assert len(rig.notifier.sent) == 1  # still no second message
    message_id, final = rig.notifier.edits[-1]
    assert message_id == "1"
    assert final.silent
    assert "⚪" in final.text
    assert "2 m 30 s" in final.text  # lifetime = until the last qualifying evaluation
    assert "#7" in final.text


async def test_duplicate_update_delivery_does_not_edit_twice() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    update = await rig.evaluation("12")
    assert await rig.service.send_opportunity(update, _context(1)) is AlertOutcome.SENT
    assert await rig.service.send_opportunity(update, _context(1)) is AlertOutcome.DUPLICATE
    assert len(rig.notifier.edits) == 1


async def test_update_survives_a_restart_because_the_message_id_is_stored() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    # A fresh service object (worker restart) over the same stores keeps editing the message.
    again = AlertService(
        evaluations=rig.repos,
        alert_log=rig.repos,
        notifier=rig.notifier,
        clock=rig.clock,
        max_age_s=120,
        messages=rig.messages,
    )
    await again.send_opportunity(await rig.evaluation("12"), _context(1))
    assert len(rig.notifier.sent) == 1
    assert len(rig.notifier.edits) == 1


async def test_edit_of_a_lost_message_resends_once_and_stores_the_new_id() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    rig.notifier.edit_error = MessageGoneError("message to edit not found")
    await rig.service.send_opportunity(await rig.evaluation("12"), _context(1))
    assert len(rig.notifier.sent) == 2  # exactly one re-send
    assert rig.messages.episodes[7].message_id == "2"
    rig.notifier.edit_error = None
    await rig.service.send_opportunity(await rig.evaluation("18"), _context(2))
    assert [message_id for message_id, _ in rig.notifier.edits] == ["2"]  # edits the new one


async def test_update_without_a_stored_message_is_sent_as_new() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("12"), _context(1))
    assert len(rig.notifier.sent) == 1
    assert rig.notifier.edits == []
    assert rig.messages.episodes[7].message_id == "1"


async def test_edit_failure_429_is_recorded_and_retryable() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    update = await rig.evaluation("12")
    rig.notifier.edit_error = NotificationError("telegram rate limit", retry_after_s=5)
    with pytest.raises(NotificationError):
        await rig.service.send_opportunity(update, _context(1))
    assert rig.repos.alerts[update][0] is AlertDeliveryStatus.FAILED
    assert len(rig.notifier.sent) == 1  # no resend on a rate limit
    rig.notifier.edit_error = None  # the Celery retry after retry_after
    assert await rig.service.send_opportunity(update, _context(1)) is AlertOutcome.SENT
    assert len(rig.notifier.edits) == 1


async def test_close_without_a_message_falls_back_to_the_event_message() -> None:
    rig = Rig()
    closed = EpisodeClosed("ABC/USDT", "a", "b", "gap", 90, "7", "0.7", 5, 0, None, episode_id=99)
    payload = event_to_payload(closed, emitted_at_ms=NOW)
    assert await rig.service.send_event(payload) is AlertOutcome.SENT
    assert rig.notifier.edits == []
    assert rig.notifier.sent[0].silent


async def test_close_of_a_deleted_message_falls_back_to_the_event_message() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    rig.notifier.edit_error = MessageGoneError("message can't be edited")
    closed = EpisodeClosed("ABC/USDT", "a", "b", "gap", 90, "7", "0.7", 5, 0, None, episode_id=7)
    assert await rig.service.send_event(event_to_payload(closed, emitted_at_ms=NOW)) is (
        AlertOutcome.SENT
    )
    assert len(rig.notifier.sent) == 2  # the NEW message and the fallback


async def test_late_close_still_edits() -> None:
    rig = Rig()
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    closed = EpisodeClosed("ABC/USDT", "a", "b", "gap", 90, "7", "0.7", 5, 0, None, episode_id=7)
    payload = event_to_payload(closed, emitted_at_ms=NOW - 3_600_000)  # sat in the queue for 1 h
    assert await rig.service.send_event(payload) is AlertOutcome.SENT
    assert len(rig.notifier.edits) == 1


async def test_cap_overflow_collapses_into_one_summary_edited_in_place() -> None:
    rig = Rig(max_per_hour=2)
    for i, symbol in enumerate(["AAA/USDT", "BBB/USDT", "CCC/USDT", "DDD/USDT", "EEE/USDT"]):
        evaluation_id = await rig.evaluation(symbol=symbol)
        outcome = await rig.service.send_opportunity(evaluation_id, _context(episode_id=10 + i))
        assert outcome is (AlertOutcome.SENT if i < 2 else AlertOutcome.SUPPRESSED)
    # 2 alerts + ONE summary message; the 3rd->5th suppression counts were edited into it.
    assert len(rig.notifier.sent) == 3
    assert "1 more" in rig.notifier.sent[2].text
    assert len(rig.notifier.edits) == 2
    assert "3 more" in rig.notifier.edits[-1][1].text
    assert rig.notifier.sent[2].silent
    suppressed = [
        e for e, (status, _) in rig.repos.alerts.items() if status is AlertDeliveryStatus.SUPPRESSED
    ]
    assert len(suppressed) == 3
    assert 12 not in rig.messages.episodes  # a suppressed NEW has no message to edit later


async def test_cap_is_per_clock_hour() -> None:
    rig = Rig(max_per_hour=1)
    first = await rig.evaluation(symbol="AAA/USDT")
    await rig.service.send_opportunity(first, _context(episode_id=1))
    blocked = await rig.evaluation(symbol="BBB/USDT")
    assert await rig.service.send_opportunity(blocked, _context(episode_id=2)) is (
        AlertOutcome.SUPPRESSED
    )
    rig.clock.now += HOUR_MS
    later = await rig.repos.add_evaluations(
        [make_evaluation(symbol="CCC/USDT", evaluated_at_ms=rig.clock.now - 1_000)]
    )
    assert await rig.service.send_opportunity(later[0], _context(episode_id=3)) is (
        AlertOutcome.SENT
    )


async def test_updates_do_not_consume_the_budget() -> None:
    rig = Rig(max_per_hour=1)
    await rig.service.send_opportunity(await rig.evaluation("8"), _context())
    update = await rig.evaluation("12")
    assert await rig.service.send_opportunity(update, _context(1)) is AlertOutcome.SENT
    assert len(rig.notifier.edits) == 1


async def test_failed_send_refunds_the_budget_slot() -> None:
    rig = Rig(max_per_hour=1)
    evaluation_id = await rig.evaluation()
    rig.notifier.error = NotificationError("boom")
    with pytest.raises(NotificationError):
        await rig.service.send_opportunity(evaluation_id, _context())
    rig.notifier.error = None
    assert await rig.service.send_opportunity(evaluation_id, _context()) is AlertOutcome.SENT


async def test_summary_failure_does_not_fail_the_alert() -> None:
    rig = Rig(max_per_hour=1)
    await rig.service.send_opportunity(await rig.evaluation(symbol="AAA/USDT"), _context(1))
    rig.notifier.error = NotificationError("telegram down")
    blocked = await rig.evaluation(symbol="BBB/USDT")
    assert await rig.service.send_opportunity(blocked, _context(episode_id=2)) is (
        AlertOutcome.SUPPRESSED
    )
