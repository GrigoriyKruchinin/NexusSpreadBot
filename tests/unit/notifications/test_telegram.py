import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from nexus.config.groups import TelegramSettings
from nexus.domain.errors import NotificationError, NotificationRejectedError
from nexus.interfaces.notifications import OutgoingMessage
from nexus.notifications.telegram import TelegramNotifier

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
