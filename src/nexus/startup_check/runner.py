"""Wiring of ``nexus check``: reads settings, runs the checks, prints the report."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text

import nexus.adapters.cex  # noqa: F401 - registers built-in exchange adapters
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.base import NexusBaseSettings
from nexus.config.groups import (
    AlertPolicySettings,
    DatabaseSettings,
    ExchangeCredentials,
    ExchangesSettings,
    KeyPolicySettings,
    SpreadSettings,
)
from nexus.persistence.db import create_engine
from nexus.startup_check.checks import (
    Item,
    check_database,
    check_telegram,
    check_venue,
    exit_code,
    safe,
)
from nexus.startup_check.messages import render
from nexus.startup_check.messages import text as message

TELEGRAM_API = "https://api.telegram.org"
DB_TIMEOUT_S = 15.0


class _RawTelegram(NexusBaseSettings):
    """Token and chat id as plain text: a missing or malformed value is a message, not a crash."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: str = ""
    chat_id: str = ""


def detect_language() -> str:
    """``[alert] language`` (config file / ``ALERT_LANGUAGE``), else ``LANG``, else English."""
    try:
        return AlertPolicySettings().language
    except Exception:  # an unreadable config is reported by the checks; stay readable
        lang = os.environ.get("LANG", "").lower()
        return "ru" if lang.startswith("ru") else "en"


def _alembic_heads() -> tuple[str, ...]:
    candidates = (Path("alembic.ini"), Path(__file__).resolve().parents[3] / "alembic.ini")
    ini = next((p for p in candidates if p.is_file()), None)
    if ini is None:
        return ()
    return tuple(ScriptDirectory.from_config(Config(str(ini))).get_heads())


async def _current_revision(settings: DatabaseSettings) -> str | None:
    engine = create_engine(settings, pooled=False)
    try:
        async with asyncio.timeout(DB_TIMEOUT_S), engine.connect() as conn:
            present = (await conn.execute(text("SELECT to_regclass('alembic_version')"))).scalar()
            if present is None:
                return None
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
            return None if row is None else str(row[0])
    finally:
        await engine.dispose()


async def _venue_items() -> list[Item]:
    try:
        exchanges = ExchangesSettings()
        key_policy = KeyPolicySettings()
        spread = SpreadSettings()
    except ValidationError as exc:
        return [Item("fail", "config_error", {"detail": safe(f"{exc.error_count()} invalid")})]
    options = AdapterOptions.from_settings(
        timeout_ms=exchanges.request_timeout_ms,
        default_taker_fee_pct=spread.default_taker_fee_pct,
    )
    items: list[Item] = []
    for venue in exchanges.enabled:
        adapter = None
        try:
            creds = ExchangeCredentials.for_exchange(venue)
        except ValidationError:
            items.append(Item("warn", "venue_incomplete", {"venue": venue, "detail": "key/secret"}))
            continue
        try:
            if creds.is_configured:
                adapter = exchange_registry.create(venue, creds, options)
        except Exception as exc:  # e.g. passphrase required but missing
            detail = safe(type(exc).__name__)
            items.append(Item("warn", "venue_incomplete", {"venue": venue, "detail": detail}))
            continue
        try:
            items.append(await check_venue(venue, adapter, creds, key_policy))
        finally:
            close = getattr(adapter, "close", None)
            if close is not None:
                await close()
    return items


async def collect(
    *,
    skip_db: bool,
    send_test: bool,
    language: str,
    client: httpx.AsyncClient | None = None,
    revision_probe: Callable[[DatabaseSettings], Awaitable[str | None]] = _current_revision,
) -> list[Item]:
    """Run all checks (Telegram, venues, database) in this order."""
    raw = _RawTelegram()
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        items = await check_telegram(
            token=raw.bot_token,
            chat_id=raw.chat_id,
            client=http,
            api_base_url=TELEGRAM_API,
            send_test=send_test,
            test_text=message("tg_test_text", language),
        )
    finally:
        if own_client:
            await http.aclose()
    items.extend(await _venue_items())
    if skip_db:
        items.append(Item("ok", "db_skipped"))
        return items
    try:
        db_settings = DatabaseSettings()
    except ValidationError:
        items.append(Item("fail", "db_password"))
        return items

    async def probe() -> str | None:
        return await revision_probe(db_settings)

    items.append(await check_database(probe, _alembic_heads()))
    return items


def run(*, skip_db: bool, send_test: bool) -> int:
    """Entry point of ``nexus check``: prints the report, returns the exit code (0 ok, 3 fatal)."""
    language = detect_language()
    items = asyncio.run(collect(skip_db=skip_db, send_test=send_test, language=language))
    print(render(items, language))  # noqa: T201 - the report is the command's output
    return exit_code(items)
