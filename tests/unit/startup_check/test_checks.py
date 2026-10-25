"""Startup check (T7): Telegram, venues, database. Fake HTTP only; all secrets are synthetic."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from nexus.adapters.key_policy import BINANCE_FORBIDDEN
from nexus.config.groups import ExchangeCredentials, KeyPolicySettings
from nexus.startup_check.checks import (
    Item,
    check_database,
    check_telegram,
    check_venue,
    exit_code,
)
from nexus.startup_check.messages import MESSAGES, render

TOKEN = "123456789" + ":" + "Zq9" * 8
KEY = "sentinel" + "-k-" + "0001" * 3
SECRET = "sentinel" + "-s-" + "0002" * 3
BOT_ID = 777

Handler = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]


def client_for(handler: Handler) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        status, body = handler(method, json.loads(request.content or b"{}"))
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def ok(result: Any) -> tuple[int, dict[str, Any]]:
    return 200, {"ok": True, "result": result}


def err(status: int, description: str) -> tuple[int, dict[str, Any]]:
    return status, {"ok": False, "description": description}


def tg_handler(
    *,
    chat_type: str = "channel",
    member: dict[str, Any] | None = None,
    getme: tuple[int, dict[str, Any]] | None = None,
    getchat: tuple[int, dict[str, Any]] | None = None,
) -> Handler:
    member = member or {
        "status": "administrator",
        "can_post_messages": True,
        "can_edit_messages": True,
    }

    def handle(method: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if method == "getMe":
            return getme or ok({"id": BOT_ID, "username": "nexus_bot"})
        if method == "getChat":
            return getchat or ok({"id": -1001, "type": chat_type})
        if method == "getChatMember":
            assert payload["user_id"] == BOT_ID
            return ok(member)
        if method == "sendMessage":
            return ok({"message_id": 1})
        raise AssertionError(method)

    return handle


async def tg(handler: Handler, *, token: str | None = TOKEN, chat: str | None = "-1001", **kw: Any):  # type: ignore[no-untyped-def]
    async with client_for(handler) as client:
        return await check_telegram(token=token, chat_id=chat, client=client, **kw)


def codes(items: list[Item]) -> list[str]:
    return [i.code for i in items]


async def test_telegram_channel_ok() -> None:
    items = await tg(tg_handler())
    assert codes(items) == ["tg_bot_ok", "tg_chat_ok"]
    assert exit_code(items) == 0


@pytest.mark.parametrize(
    ("token", "chat", "expected"),
    [
        (None, "-1", "tg_token_missing"),
        ("", "-1", "tg_token_missing"),
        ("123456789:AAFakeFakeFakeFakeFakeFakeFake", "-1", "tg_token_placeholder"),
        ("not-a-token", "-1", "tg_token_format"),
        (TOKEN, None, "tg_chat_missing"),
        (TOKEN, "my channel", "tg_chat_format"),
    ],
)
async def test_telegram_config_errors_need_no_network(
    token: str | None, chat: str | None, expected: str
) -> None:
    def boom(method: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        raise AssertionError("no request expected")

    items = await tg(boom, token=token, chat=chat)
    assert expected in codes(items)
    assert exit_code(items) == 3


async def test_token_rejected_401() -> None:
    items = await tg(tg_handler(getme=err(401, "Unauthorized")))
    assert codes(items) == ["tg_token_rejected"]
    assert exit_code(items) == 3


async def test_chat_not_found_and_username_hint() -> None:
    bad = err(400, "Bad Request: chat not found")
    assert codes(await tg(tg_handler(getchat=bad)))[-1] == "tg_chat_not_found"
    assert codes(await tg(tg_handler(getchat=bad), chat="@somename"))[-1] == "tg_chat_username"


async def test_bot_kicked_403() -> None:
    items = await tg(tg_handler(getchat=err(403, "Forbidden: bot was kicked")))
    assert codes(items)[-1] == "tg_bot_kicked"


async def test_channel_bot_not_admin() -> None:
    items = await tg(tg_handler(member={"status": "member"}))
    assert codes(items)[-1] == "tg_not_admin"
    assert exit_code(items) == 3


async def test_channel_admin_without_edit_right() -> None:
    member = {"status": "administrator", "can_post_messages": True, "can_edit_messages": False}
    items = await tg(tg_handler(member=member))
    assert codes(items)[-1] == "tg_cannot_post"
    assert items[-1].params["detail"] == "can_edit_messages"


async def test_channel_creator_ok_and_group_member_ok() -> None:
    assert exit_code(await tg(tg_handler(member={"status": "creator"}))) == 0
    assert exit_code(await tg(tg_handler(chat_type="supergroup", member={"status": "member"}))) == 0


async def test_group_restricted_bot_fails() -> None:
    member = {"status": "restricted", "can_send_messages": False}
    items = await tg(tg_handler(chat_type="group", member=member))
    assert codes(items)[-1] == "tg_cannot_send"


async def test_private_chat_skips_member_check() -> None:
    def handle(method: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        assert method != "getChatMember"
        return tg_handler(chat_type="private")(method, payload)

    assert exit_code(await tg(handle, chat="123456789")) == 0


async def test_send_test_only_when_asked_and_allowed() -> None:
    sent: list[str] = []

    def handle(method: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        sent.append(method)
        return tg_handler()(method, payload)

    await tg(handle)
    assert "sendMessage" not in sent
    items = await tg(handle, send_test=True)
    assert codes(items)[-1] == "tg_test_sent"
    sent.clear()
    await tg(tg_handler(member={"status": "member"}), send_test=True)
    assert "sendMessage" not in sent


async def test_unreachable_is_a_warning_without_token_in_text() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        items = await check_telegram(token=TOKEN, chat_id="-1001", client=client)
    assert codes(items) == ["tg_unreachable"]
    assert exit_code(items) == 0
    for lang in ("en", "ru"):
        assert TOKEN not in render(items, lang)


# ------------------------------------------------------------------ venues


class FakeAdapter:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload, self.error, self.calls = payload, error, 0

    async def fetch_key_info(self) -> Any:
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def creds(configured: bool = True) -> ExchangeCredentials:
    if not configured:
        return ExchangeCredentials()
    return ExchangeCredentials(api_key=KEY, api_secret=SECRET)  # type: ignore[arg-type]


BINANCE_OK = {"enableReading": True, "ipRestrict": True, **dict.fromkeys(BINANCE_FORBIDDEN, False)}
POLICY = KeyPolicySettings(strict=False, _env_file=None)


async def test_venue_without_key_is_public_and_makes_no_call() -> None:
    adapter = FakeAdapter()
    item = await check_venue("binance", adapter, creds(False), POLICY)
    assert (item.status, item.code, adapter.calls) == ("ok", "venue_public", 0)


async def test_venue_good_key_is_keyed() -> None:
    item = await check_venue("binance", FakeAdapter(BINANCE_OK), creds(), POLICY)
    assert item.code == "venue_keyed"


async def test_venue_withdraw_enabled_falls_back_to_public() -> None:
    payload = {**BINANCE_OK, "enableWithdrawals": True}
    item = await check_venue("binance", FakeAdapter(payload), creds(), POLICY)
    assert (item.status, item.code) == ("warn", "venue_withdraw")
    assert exit_code([item]) == 0
    assert "PUBLIC" in render([item], "en")
    assert "ПУБЛИЧНОМ" in render([item], "ru")


async def test_venue_rejected_key_warns_and_scrubs_error() -> None:
    adapter = FakeAdapter(error=RuntimeError(f"401 invalid key {KEY} {SECRET}"))
    item = await check_venue("okx", adapter, creds(), POLICY)
    assert (item.status, item.code) == ("warn", "venue_rejected")
    for lang in ("en", "ru"):
        out = render([item], lang)
        assert KEY not in out
        assert SECRET not in out
        assert "okx" in out


async def test_one_bad_venue_does_not_stop_the_next() -> None:
    bad = await check_venue("okx", FakeAdapter(error=RuntimeError("x")), creds(), POLICY)
    good = await check_venue("binance", FakeAdapter(BINANCE_OK), creds(), POLICY)
    assert (bad.code, good.code) == ("venue_rejected", "venue_keyed")


async def test_venue_policy_violation_without_withdraw() -> None:
    payload = {**BINANCE_OK, "enableFutures": True}
    item = await check_venue("binance", FakeAdapter(payload), creds(), POLICY)
    assert item.code == "venue_policy"
    assert KEY not in render([item], "en")


# ------------------------------------------------------------------ database


async def test_database_states() -> None:
    async def at(rev: str | None) -> str | None:
        return rev

    async def down() -> str | None:
        raise ConnectionRefusedError(f"password={SECRET} host=db")

    assert (await check_database(lambda: at("abc"), ("abc",))).code == "db_ok"
    assert (await check_database(lambda: at(None), ("abc",))).code == "db_not_migrated"
    assert (await check_database(lambda: at("old"), ("abc",))).code == "db_outdated"
    unreachable = await check_database(down, ("abc",))
    assert unreachable.code == "db_unreachable"
    assert SECRET not in render([unreachable], "en")
    assert exit_code([unreachable]) == 3


# ------------------------------------------------------------------ texts


def test_every_message_has_both_languages_and_renders() -> None:
    for code, (en, ru) in MESSAGES.items():
        assert en.strip()
        assert ru.strip()
        assert any("а" <= c.lower() <= "я" for c in ru), code
        assert {f for f in ("{docs}", "{venue}", "{detail}") if f in en} == {
            f for f in ("{docs}", "{venue}", "{detail}") if f in ru
        }, code
        render([Item("ok", code, {"venue": "v", "detail": "d"})], "en")
        render([Item("ok", code, {"venue": "v", "detail": "d"})], "ru")


def test_render_summary_and_language_fallback() -> None:
    assert "FIX" in render([Item("fail", "tg_token_missing")], "en")
    assert "исправьте" in render([Item("fail", "tg_token_missing")], "ru")
    assert "warnings" in render([Item("warn", "venue_rejected", {"venue": "x"})], "en")
    assert "you can start" in render([Item("ok", "db_skipped")], "de")


async def test_check_agrees_with_scanner_policy_in_default_mode() -> None:
    """T9: `nexus check` uses the scanner's policy function: withdraw key -> warn, not fail."""
    from nexus.adapters.key_policy import verify_key_policies

    payload = {**BINANCE_OK, "enableWithdrawals": True}
    item = await check_venue("binance", FakeAdapter(payload), creds(), POLICY)
    report = await verify_key_policies(
        {"binance": FakeAdapter(payload)}, {"binance": creds()}, POLICY
    )
    assert item.status == "warn"
    assert report.rejected_venues == ("binance",)


async def test_unverifiable_venue_is_a_warning_in_default_mode() -> None:
    kucoin = {"code": "200000", "data": {"permission": "General"}}
    item = await check_venue("kucoin", FakeAdapter(kucoin), creds(), POLICY)
    assert (item.status, item.code) == ("warn", "venue_keyed_warn")


async def test_strict_mode_fails_the_check() -> None:
    strict = KeyPolicySettings(strict=True)
    payload = {**BINANCE_OK, "enableWithdrawals": True}
    item = await check_venue("binance", FakeAdapter(payload), creds(), strict)
    assert (item.status, item.code) == ("fail", "venue_withdraw")
    assert exit_code([item]) == 3
    unbound = {**BINANCE_OK, "ipRestrict": False}
    assert (await check_venue("binance", FakeAdapter(unbound), creds(), strict)).status == "fail"
    relaxed = await check_venue("binance", FakeAdapter(unbound), creds(), POLICY)
    assert (relaxed.status, relaxed.code) == ("warn", "venue_keyed_warn")
