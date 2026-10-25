"""The individual startup checks. Each returns :class:`Item` objects; none prints or logs.

Secrets: the Telegram token sits in request URLs, so transport errors are reduced to the exception
class name; exchange keys are only handed to the adapter, and key-policy results are rule names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import httpx

from nexus.adapters.key_policy import (
    NO_POLICY,
    REQUEST_FAILED,
    KeyAssessment,
    assess_venue_key,
)
from nexus.config.groups import ExchangeCredentials, KeyPolicySettings

Status = Literal["ok", "warn", "fail"]

EXIT_OK: Final = 0
EXIT_FATAL_CONFIG: Final = 3
"""Same code as a key-policy refusal: a restart cannot fix it (D-01)."""

_TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{20,}")
_PLACEHOLDER_RE = re.compile(r"fake|your|example|changeme|xxxx", re.IGNORECASE)
_CHAT_RE = re.compile(r"-?\d+")
_CHANNEL_RIGHTS: Final = ("can_post_messages", "can_edit_messages")
_SAFE = re.compile(r"[^A-Za-z0-9_:., -]")


@dataclass(frozen=True, slots=True)
class Item:
    """One line of the report: ``code`` selects the bilingual text, ``params`` fill it."""

    status: Status
    code: str
    params: Mapping[str, str] = field(default_factory=dict)


def exit_code(items: list[Item]) -> int:
    """3 if any item failed (fatal configuration), else 0 (warnings do not block)."""
    return EXIT_FATAL_CONFIG if any(i.status == "fail" for i in items) else EXIT_OK


def safe(value: object) -> str:
    """Short text with only harmless characters (for exception names, rule names)."""
    return _SAFE.sub("", str(value))[:120]


# ------------------------------------------------------------------ telegram


async def _call(
    client: httpx.AsyncClient, base: str, token: str, method: str, payload: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """POST a Bot API method; ``(0, {})`` is never returned, transport errors raise."""
    response = await client.post(f"{base}/bot{token}/{method}", json=payload)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def _description(body: dict[str, Any]) -> str:
    return str(body.get("description") or "").lower()


async def check_telegram(
    *,
    token: str | None,
    chat_id: str | None,
    client: httpx.AsyncClient,
    api_base_url: str = "https://api.telegram.org",
    send_test: bool = False,
    test_text: str = "Nexus: setup check OK",
) -> list[Item]:
    """Validate the bot token, the chat and (for channels) the bot's rights."""
    token = (token or "").strip()
    chat = (chat_id or "").strip()
    items: list[Item] = []
    if not token:
        items.append(Item("fail", "tg_token_missing"))
    elif _PLACEHOLDER_RE.search(token):
        items.append(Item("fail", "tg_token_placeholder"))
    elif not _TOKEN_RE.fullmatch(token):
        items.append(Item("fail", "tg_token_format"))
    if not chat:
        items.append(Item("fail", "tg_chat_missing"))
    elif not (chat.startswith("@") or _CHAT_RE.fullmatch(chat)):
        items.append(Item("fail", "tg_chat_format"))
    if items:
        return items
    try:
        return await _check_online(client, api_base_url, token, chat, send_test, test_text)
    except httpx.HTTPError as exc:  # never chain: the URL holds the token
        return [Item("warn", "tg_unreachable", {"detail": type(exc).__name__})]


async def _check_online(
    client: httpx.AsyncClient, base: str, token: str, chat: str, send_test: bool, test_text: str
) -> list[Item]:
    status, body = await _call(client, base, token, "getMe", {})
    if status in (401, 404):
        return [Item("fail", "tg_token_rejected")]
    result = body.get("result")
    if status != 200 or not body.get("ok") or not isinstance(result, dict):
        return [Item("warn", "tg_api_error", {"detail": str(status)})]
    items = [Item("ok", "tg_bot_ok", {"detail": safe(result.get("username", "?"))})]
    bot_id = result.get("id")

    status, body = await _call(client, base, token, "getChat", {"chat_id": chat})
    desc = _description(body)
    if status == 403 or "kicked" in desc or "blocked" in desc:
        return [*items, Item("fail", "tg_bot_kicked")]
    if status in (400, 404) or "not found" in desc:
        code = "tg_chat_username" if chat.startswith("@") else "tg_chat_not_found"
        return [*items, Item("fail", code)]
    chat_info = body.get("result")
    if status != 200 or not isinstance(chat_info, dict):
        return [*items, Item("warn", "tg_api_error", {"detail": str(status)})]
    kind = safe(chat_info.get("type", "?"))
    verdict = await _check_rights(client, base, token, chat, kind, bot_id)
    items.append(verdict or Item("ok", "tg_chat_ok", {"detail": kind}))
    if send_test and verdict is None:
        items.append(await _send_test(client, base, token, chat, test_text))
    return items


async def _check_rights(
    client: httpx.AsyncClient, base: str, token: str, chat: str, kind: str, bot_id: object
) -> Item | None:
    """``None`` = bot may post (and edit, for channels); otherwise the failing item."""
    if kind == "private" or not isinstance(bot_id, int):
        return None
    status, body = await _call(
        client, base, token, "getChatMember", {"chat_id": chat, "user_id": bot_id}
    )
    member = body.get("result")
    if status != 200 or not isinstance(member, dict):
        return Item("warn", "tg_api_error", {"detail": str(status)})
    role = member.get("status")
    if role in ("left", "kicked"):
        return Item("fail", "tg_bot_kicked")
    if role == "creator":
        return None
    if kind == "channel":
        if role != "administrator":
            return Item("fail", "tg_not_admin")
        missing = [r for r in _CHANNEL_RIGHTS if member.get(r) is not True]
        return Item("fail", "tg_cannot_post", {"detail": ", ".join(missing)}) if missing else None
    if role == "restricted" and member.get("can_send_messages") is False:
        return Item("fail", "tg_cannot_send")
    return None


async def _send_test(
    client: httpx.AsyncClient, base: str, token: str, chat: str, text: str
) -> Item:
    status, body = await _call(client, base, token, "sendMessage", {"chat_id": chat, "text": text})
    if status == 200 and body.get("ok") is True:
        return Item("ok", "tg_test_sent")
    return Item("fail", "tg_test_failed", {"detail": str(status)})


# ------------------------------------------------------------------ venues


def _is_withdraw_rule(rule: str) -> bool:
    lowered = rule.lower()
    return "withdraw" in lowered or "transfer" in lowered


async def check_venue(
    venue: str,
    adapter: object | None,
    credentials: ExchangeCredentials | None,
    key_policy: KeyPolicySettings,
) -> Item:
    """Mode of one venue, judged by the same policy function as the scanner.

    Never raises and never stops other venues; reads only (one signed GET). A rejected key is a
    warning (the scanner runs that venue in public mode), or a failure in strict mode.
    """
    if credentials is None or not credentials.is_configured:
        return Item("ok", "venue_public", {"venue": venue})
    if adapter is None:
        return Item("fail" if key_policy.strict else "warn", "venue_rejected", {"venue": venue})
    try:
        assessment = await assess_venue_key(venue, adapter, credentials, key_policy)
    except Exception:  # defensive: a venue problem must not stop the check
        assessment = KeyAssessment(violations=(REQUEST_FAILED,))
    if assessment is None:  # unreachable: credentials are configured
        return Item("ok", "venue_public", {"venue": venue})
    if not assessment.accepted:
        rules = assessment.violations
        severity: Status = "fail" if key_policy.strict else "warn"
        detail = safe(", ".join(rules))
        params = {"venue": venue, "detail": detail}
        if any(_is_withdraw_rule(r) for r in rules):
            return Item(severity, "venue_withdraw", params)
        if rules in ((REQUEST_FAILED,), (NO_POLICY,)):
            return Item(severity, "venue_rejected", {"venue": venue})
        return Item(severity, "venue_policy", params)
    if assessment.warnings:
        detail = safe(", ".join(assessment.warnings))
        return Item("warn", "venue_keyed_warn", {"venue": venue, "detail": detail})
    return Item("ok", "venue_keyed", {"venue": venue})


# ------------------------------------------------------------------ database


async def check_database(probe_version: Any, heads: tuple[str, ...]) -> Item:
    """``probe_version()`` returns the current alembic revision (or ``None`` if no schema)."""
    try:
        current = await probe_version()
    except Exception as exc:  # message may hold host/user: class name only
        return Item("fail", "db_unreachable", {"detail": safe(type(exc).__name__)})
    if current is None:
        return Item("fail", "db_not_migrated")
    if heads and current not in heads:
        return Item("fail", "db_outdated", {"detail": safe(current)})
    return Item("ok", "db_ok", {"detail": safe(current)})
