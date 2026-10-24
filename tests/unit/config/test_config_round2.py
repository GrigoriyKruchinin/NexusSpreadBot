"""A7 review round 2: replace semantics, hash scope, key-name redaction, provenance coverage."""

import re
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from nexus.config import ExchangesSettings, SpreadSettings
from nexus.config.file import ConfigFileError
from nexus.config.groups import PaperSettings
from nexus.config.provenance import (
    dotenv_setting_names,
    log_settings_provenance,
    main,
    settings_hash,
)

ROOT = Path(__file__).resolve().parents[3]
TOKEN_KEY = "123456789:AAH-abcdefghijklmnopqrstuvwxyz0123"


def _toml(tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cfg.toml"
    path.write_text(body)
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(path))
    return path


# ------------------------------------------------------------------ TL1: replace, no merge
def test_env_dict_replaces_toml_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, "[spread]\ntransfer_tax_pct = { LUNC = 1.5, USTC = 1.5 }\n", monkeypatch)
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"FOO":"2"}')
    assert set(SpreadSettings().transfer_tax_pct) == {"FOO"}


def test_dotenv_dict_replaces_toml_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, "[spread]\ntransfer_tax_pct = { LUNC = 1.5, USTC = 1.5 }\n", monkeypatch)
    Path(".env").write_text('SPREAD_TRANSFER_TAX_PCT={"FOO":"2"}\n')
    assert set(SpreadSettings().transfer_tax_pct) == {"FOO"}


def test_dotenv_ignored_in_container_so_toml_dict_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _toml(tmp_path, "[spread]\ntransfer_tax_pct = { LUNC = 1.5 }\n", monkeypatch)
    Path(".env").write_text('SPREAD_TRANSFER_TAX_PCT={"FOO":"2"}\n')
    monkeypatch.setenv("NEXUS_RUNTIME", "container")
    assert set(SpreadSettings().transfer_tax_pct) == {"LUNC"}


def test_env_list_replaces_toml_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, '[exchanges]\nenabled = ["okx", "kucoin", "mexc"]\n', monkeypatch)
    monkeypatch.setenv("EXCHANGES_ENABLED", "binance,okx")
    assert ExchangesSettings().enabled == ("binance", "okx")


def test_empty_env_dict_does_not_drop_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, "[spread]\ntransfer_tax_pct = { LUNC = 1.5 }\n", monkeypatch)
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", "")
    assert set(SpreadSettings().transfer_tax_pct) == {"LUNC"}


# ------------------------------------------------------------------ TL2: names of .env settings
def test_dotenv_setting_names_are_names_only(tmp_path: Path) -> None:
    Path(".env").write_text(
        "LOG_LEVEL=DEBUG\nSPREAD_MIN_NET_PROFIT_USD=\nTELEGRAM_BOT_TOKEN=hush-hush\n"
        "paper_capital_usd=5\n"
    )
    assert dotenv_setting_names() == ["LOG_LEVEL", "PAPER_CAPITAL_USD"]


def test_dotenv_setting_names_without_file() -> None:
    assert dotenv_setting_names() == []


def test_helper_prints_names_never_values(capsys: pytest.CaptureFixture[str]) -> None:
    Path(".env").write_text("LOG_LEVEL=value-that-must-not-print\n")
    assert main() == 0
    out = capsys.readouterr().out
    assert "LOG_LEVEL" in out
    assert "value-that-must-not-print" not in out


def test_helper_silent_success_when_clean(capsys: pytest.CaptureFixture[str]) -> None:
    Path(".env").write_text("POSTGRES_PASSWORD=x\n")
    assert main() == 0
    assert "LOG_" not in capsys.readouterr().out


# ------------------------------------------------------------------ TL3: hash scope
def test_hash_ignores_deployment_location(monkeypatch: pytest.MonkeyPatch) -> None:
    base = settings_hash()
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_POOL_SIZE", "11")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert settings_hash() == base


def test_hash_normalizes_decimal_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_CAPITAL_USD", "20000")
    plain = settings_hash()
    monkeypatch.setenv("PAPER_CAPITAL_USD", "20000.0")
    assert settings_hash() == plain
    monkeypatch.setenv("PAPER_CAPITAL_USD", "2E+4")
    assert settings_hash() == plain
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"A":"1.50"}')
    taxed = settings_hash()
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"A":"1.5"}')
    assert settings_hash() == taxed


def test_hash_still_tracks_strategy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    base = settings_hash()
    monkeypatch.setenv("PAPER_CAPITAL_USD", "123")
    assert settings_hash() != base
    assert PaperSettings().capital_usd == 123


# ------------------------------------------------------------------ L1: key names redaction
@pytest.mark.parametrize(
    "body",
    [
        f'[telegram]\n"{TOKEN_KEY}" = 1\n',
        f'["{TOKEN_KEY}"]\nx = 1\n',
        f'[spread]\n"{TOKEN_KEY}" = 1\n',
        '[spread]\n"has space and $ymbols" = 1\n',
    ],
)
def test_unusual_names_are_not_echoed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    _toml(tmp_path, body, monkeypatch)
    with pytest.raises(ConfigFileError) as err:
        SpreadSettings()
    message = str(err.value)
    assert TOKEN_KEY not in message
    assert "AAH-abcdef" not in message
    assert "has space" not in message


def test_unusual_key_placeholder_and_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, '[spread]\n"has space" = 1\n', monkeypatch)
    with pytest.raises(ConfigFileError, match=r"<unprintable key>"):
        SpreadSettings()


def test_ordinary_names_still_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _toml(tmp_path, "[spread]\ntypo-key_1 = 1\n", monkeypatch)
    with pytest.raises(ConfigFileError, match=r"\[spread\] typo-key_1: unknown key"):
        SpreadSettings()


# ------------------------------------------------------------------ L2: gitleaks rule
def _gitleaks_rule(rule_id: str) -> re.Pattern[str]:
    import tomllib

    rules = tomllib.loads((ROOT / ".gitleaks.toml").read_text())["rules"]
    (rule,) = [r for r in rules if r["id"] == rule_id]
    return re.compile(rule["regex"])


@pytest.mark.parametrize(
    "line",
    [
        'bot_token = "abc"',
        '"bot_token" = "abc"',
        'telegram.bot_token = "abc"',
        'telegram = { bot_token = "abc" }',
        'bot-token = "abc"',
        'chat_id = "1"',
        'api_key="k"',
        "  Password = x",
    ],
)
def test_gitleaks_key_rule_matches_variants(line: str) -> None:
    assert _gitleaks_rule("nexus-config-toml-secret-key").search(line)


def test_gitleaks_key_rule_clean_on_repo_file() -> None:
    text = (ROOT / "config" / "nexus.toml").read_text()
    assert not _gitleaks_rule("nexus-config-toml-secret-key").search(text)
    assert not _gitleaks_rule("nexus-config-toml-credential-url").search(text)


def test_gitleaks_url_rule_is_case_insensitive() -> None:
    assert _gitleaks_rule("nexus-config-toml-credential-url").search("HTTPS://u:pw@h")


# ------------------------------------------------------------------ TL5 / L3: beat & migrator log
def test_beat_logs_settings_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.workers.app import _log_beat_settings

    with capture_logs() as logs:
        _log_beat_settings()
    (event,) = [e for e in logs if e["event"] == "settings_loaded"]
    assert event["service"] == "beat"


def test_migrator_logs_settings_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    with capture_logs() as logs:
        log_settings_provenance("migrator")
    (event,) = [e for e in logs if e["event"] == "settings_loaded"]
    assert event["service"] == "migrator"


def test_migrations_env_calls_provenance() -> None:
    src = (ROOT / "src" / "nexus" / "persistence" / "migrations" / "env.py").read_text()
    assert 'log_settings_provenance("migrator")' in src
