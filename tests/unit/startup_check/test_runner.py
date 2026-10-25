"""``nexus check`` wiring: env -> report -> exit code (fake HTTP, no network, no database)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus import cli
from nexus.adapters.registry import exchange_registry
from nexus.config.groups import DatabaseSettings
from nexus.startup_check import runner

from .test_checks import TOKEN, client_for, tg_handler


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no .env / alembic.ini picked up
    monkeypatch.setenv("NEXUS_RUNTIME", "container")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "POSTGRES_PASSWORD", "ALERT_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EXCHANGES_ENABLED", "binance,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "")
    monkeypatch.setattr(runner, "_alembic_heads", lambda: ())


async def test_collect_ok_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001")
    async with client_for(tg_handler()) as client:
        items = await runner.collect(skip_db=True, send_test=False, language="en", client=client)
    assert [i.code for i in items] == [
        "tg_bot_ok",
        "tg_chat_ok",
        "venue_public",
        "venue_public",
        "db_skipped",
    ]


async def test_collect_db_missing_password_and_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001")
    async with client_for(tg_handler()) as client:
        items = await runner.collect(skip_db=False, send_test=False, language="en", client=client)
        assert items[-1].code == "db_password"
        monkeypatch.setenv("POSTGRES_PASSWORD", "x" * 16)

        async def probe(settings: DatabaseSettings) -> str | None:
            return "rev1"

        items = await runner.collect(
            skip_db=False, send_test=False, language="en", client=client, revision_probe=probe
        )
    assert items[-1].code == "db_ok"  # no alembic.ini in cwd -> heads unknown -> any revision


def test_cli_exit_code_and_language(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ALERT_LANGUAGE", "ru")
    assert cli.main(["check", "--no-db"]) == 3  # token and chat missing
    out = capsys.readouterr().out
    assert "TELEGRAM_BOT_TOKEN пуст" in out
    assert "[FAIL]" in out
    assert "docs/guides/quickstart.md" in out


def test_detect_language_falls_back_to_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner.detect_language() == "en"
    monkeypatch.setenv("ALERT_LANGUAGE", "bogus")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    assert runner.detect_language() == "ru"


async def test_venue_items_fall_back_per_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_checks import KEY, SECRET, FakeAdapter

    monkeypatch.setenv("BINANCE_API_KEY", KEY)
    monkeypatch.setenv("BINANCE_API_SECRET", SECRET)
    monkeypatch.setenv("OKX_API_KEY", KEY)  # secret missing -> incomplete
    closed: list[str] = []

    class Closing(FakeAdapter):
        async def close(self) -> None:
            closed.append("x")

    monkeypatch.setattr(
        exchange_registry,
        "create",
        lambda venue, creds, options: Closing(error=RuntimeError(f"bad {KEY} {SECRET}")),
    )
    items = await runner._venue_items()
    assert [i.code for i in items] == ["venue_rejected", "venue_incomplete"]
    assert closed == ["x"]
    assert KEY not in repr(items)
    assert SECRET not in repr(items)


async def test_venue_adapter_creation_error_is_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    from .test_checks import KEY, SECRET

    monkeypatch.setenv("BINANCE_API_KEY", KEY)
    monkeypatch.setenv("BINANCE_API_SECRET", SECRET)

    def boom(*args: object) -> None:
        raise ValueError(f"passphrase required {SECRET}")

    monkeypatch.setattr(exchange_registry, "create", boom)
    items = await runner._venue_items()
    assert items[0].code == "venue_incomplete"
    assert SECRET not in repr(items)
