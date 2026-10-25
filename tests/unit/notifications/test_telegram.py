import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from nexus.config.groups import TelegramSettings
from nexus.domain.errors import MessageGoneError, NotificationError, NotificationRejectedError
from nexus.interfaces.notifications import OutgoingMessage
from nexus.notifications.rate_limit import SendRateLimiter
from nexus.notifications.telegram import TelegramNotifier
from tests.fakes import FakeClock

TOKEN = "123456789:AAHabcdefghijklmnopqrstuvwxyz0123456"


def _settings(**overrides: Any) -> TelegramSettings:
    values: dict[str, Any] = {"bot_token": SecretStr(TOKEN), "chat_id": "-100123"}
    values.update(overrides)
    return TelegramSettings(**values)


def _notifier(handler: Any, **overrides: Any) -> tuple[TelegramNotifier, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return TelegramNotifier(_settings(**overrides), client=client), seen


async def test_send_success_payload() -> None:
    notifier, seen = _notifier(
        lambda _: httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )
    receipt = await notifier.send(OutgoingMessage(text="<b>hi</b>", silent=True))
    assert receipt.message_id == "77"
    assert receipt.channel == "telegram"
    request = seen[0]
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert body == {
        "chat_id": "-100123",
        "text": "<b>hi</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": True,
    }
    await notifier.close()


async def test_missing_message_id_is_none_not_the_string_none() -> None:
    notifier, _ = _notifier(lambda _: httpx.Response(200, json={"ok": True, "result": {}}))
    assert (await notifier.send(OutgoingMessage(text="x"))).message_id is None


async def test_rate_limit_carries_retry_after() -> None:
    notifier, _ = _notifier(
        lambda _: httpx.Response(
            429,
            json={
                "ok": False,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            },
        )
    )
    with pytest.raises(NotificationError) as exc_info:
        await notifier.send(OutgoingMessage(text="x"))
    assert exc_info.value.retry_after_s == 7
    assert not isinstance(exc_info.value, NotificationRejectedError)


async def test_bad_request_is_rejected_permanently() -> None:
    notifier, _ = _notifier(
        lambda _: httpx.Response(
            400, json={"ok": False, "description": "Bad Request: can't parse entities"}
        )
    )
    with pytest.raises(NotificationRejectedError, match="parse entities"):
        await notifier.send(OutgoingMessage(text="<b"))


async def test_server_error_is_retryable() -> None:
    notifier, _ = _notifier(lambda _: httpx.Response(502, text="bad gateway"))
    with pytest.raises(NotificationError) as exc_info:
        await notifier.send(OutgoingMessage(text="x"))
    assert not isinstance(exc_info.value, NotificationRejectedError)


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
async def test_transport_errors_never_leak_token(error: Exception) -> None:
    def raise_error(request: httpx.Request) -> httpx.Response:
        raise type(error)(f"failed {request.url}")

    notifier, _ = _notifier(raise_error)
    with pytest.raises(NotificationError) as exc_info:
        await notifier.send(OutgoingMessage(text="x"))
    assert TOKEN not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


async def test_edit_payload_and_receipt() -> None:
    notifier, seen = _notifier(
        lambda _: httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )
    receipt = await notifier.edit("77", OutgoingMessage(text="<b>new</b>"))
    assert receipt.message_id == "77"
    assert seen[0].url.path == f"/bot{TOKEN}/editMessageText"
    body = json.loads(seen[0].content)
    assert body == {
        "chat_id": "-100123",
        "message_id": 77,
        "text": "<b>new</b>",
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }


async def test_edit_returns_the_id_when_the_reply_is_true() -> None:
    # Telegram answers `result: true` for edits of inline messages; the id is then the input.
    notifier, _ = _notifier(lambda _: httpx.Response(200, json={"ok": True, "result": True}))
    assert (await notifier.edit("5", OutgoingMessage(text="x"))).message_id == "5"


async def test_edit_not_modified_is_success() -> None:
    notifier, _ = _notifier(
        lambda _: httpx.Response(
            400,
            json={
                "ok": False,
                "description": "Bad Request: message is not modified: specified new message "
                "content and reply markup are exactly the same",
            },
        )
    )
    receipt = await notifier.edit("9", OutgoingMessage(text="same"))
    assert receipt.message_id == "9"


@pytest.mark.parametrize(
    "description",
    [
        "Bad Request: message to edit not found",
        "Bad Request: message can't be edited",
        "Bad Request: MESSAGE_ID_INVALID",
    ],
)
async def test_edit_of_a_gone_message_raises_message_gone(description: str) -> None:
    notifier, _ = _notifier(
        lambda _: httpx.Response(400, json={"ok": False, "description": description})
    )
    with pytest.raises(MessageGoneError):
        await notifier.edit("9", OutgoingMessage(text="x"))


async def test_edit_other_rejection_stays_a_plain_rejection() -> None:
    notifier, _ = _notifier(
        lambda _: httpx.Response(
            400, json={"ok": False, "description": "Bad Request: can't parse entities"}
        )
    )
    with pytest.raises(NotificationRejectedError) as exc_info:
        await notifier.edit("9", OutgoingMessage(text="<b"))
    assert not isinstance(exc_info.value, MessageGoneError)


async def test_429_blocks_the_limiter_and_carries_retry_after() -> None:
    clock = FakeClock()
    limiter = SendRateLimiter(monotonic=clock.now, sleep=clock.sleep, max_wait_s=100)
    notifier, _ = _notifier(
        lambda _: httpx.Response(
            429, json={"ok": False, "description": "Too Many", "parameters": {"retry_after": 30}}
        )
    )
    notifier._limiter = limiter
    with pytest.raises(NotificationError) as exc_info:
        await notifier.edit("9", OutgoingMessage(text="x"))
    assert exc_info.value.retry_after_s == 30
    await limiter.acquire()  # the next call waits behind retry_after
    assert clock.slept[-1] >= 29
