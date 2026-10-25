"""config/nexus.toml: loader, priority, fail-closed guard, provenance, hash (A7)."""

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from nexus.config import (
    AlertsWorkerSettings,
    DatabaseSettings,
    ExchangesSettings,
    LoggingSettings,
    MigratorSettings,
    SpreadSettings,
    TelegramSettings,
)
from nexus.config import groups as groups_module
from nexus.config.base import NexusBaseSettings
from nexus.config.file import (
    _DENY_EXACT,
    TOML_ALLOWED,
    ConfigFileError,
    _denied,
)
from nexus.config.groups import AlertPolicySettings
from nexus.config.provenance import env_overridden_names, log_settings_provenance, settings_hash
from tests.db_guard import UnsafeDatabaseError, assert_test_database

ROOT = Path(__file__).resolve().parents[3]
REPO_TOML = ROOT / "config" / "nexus.toml"
PW = "unit-test-password-123"
SECRET_VALUE = "s3cr3t-value-that-must-never-leak"


def _write(tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cfg.toml"
    path.write_text(body)
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(path))
    return path


def _groups() -> list[type[NexusBaseSettings]]:
    return [
        obj
        for obj in vars(groups_module).values()
        if isinstance(obj, type)
        and issubclass(obj, NexusBaseSettings)
        and obj is not NexusBaseSettings
    ]


# ------------------------------------------------------------------ load & priority
def test_toml_value_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    assert SpreadSettings().min_net_profit_usd == Decimal(9)


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_USD", "11")
    assert SpreadSettings().min_net_profit_usd == Decimal(11)


def test_empty_env_does_not_override_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_USD", "")  # compose passes "" for unset
    assert SpreadSettings().min_net_profit_usd == Decimal(9)


def test_toml_overrides_code_default_and_init_overrides_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, '[log]\nlevel = "DEBUG"\n', monkeypatch)
    assert LoggingSettings().level == "DEBUG"
    assert LoggingSettings(level="ERROR").level == "ERROR"


def test_list_and_dict_values_from_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path,
        '[exchanges]\nenabled = ["okx", "kucoin"]\n[spread]\ntransfer_tax_pct = { ABC = 2.5 }\n',
        monkeypatch,
    )
    assert ExchangesSettings().enabled == ("okx", "kucoin")
    assert SpreadSettings().transfer_tax_pct == {"ABC": Decimal("2.5")}


def test_other_groups_do_not_see_foreign_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n[log]\njson_format = false\n", monkeypatch)
    assert LoggingSettings().level == "INFO"
    assert LoggingSettings().json_format is False


def test_empty_file_gives_code_defaults() -> None:
    assert SpreadSettings().min_net_profit_pct == Decimal("0.3")


def test_repo_toml_equals_code_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default value changes: the committed file must reproduce every code default."""
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)
    skipped = {"TelegramSettings", "ExchangeCredentials", "KeyPolicySettings"}
    classes = [cls for cls in _groups() if cls.__name__ not in skipped]

    def dump() -> list[dict[str, object]]:
        telegram = TelegramSettings(bot_token=SecretStr("0:" + "a" * 20), chat_id="0")
        return [telegram.model_dump(), *(cls().model_dump() for cls in classes)]

    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(REPO_TOML))
    with_file = dump()
    monkeypatch.delenv("NEXUS_CONFIG_FILE")  # default path in the empty tmp cwd: absent
    without_file = dump()
    assert with_file == without_file


def test_repo_toml_completeness_and_classification() -> None:
    data = tomllib.loads(REPO_TOML.read_text())
    present = {f"{t}_{k}".upper() for t, body in data.items() for k in body}
    assert present == TOML_ALLOWED
    # Every settings field is either in the file or deliberately SECRET / ENV-ONLY.
    not_settings = {name for name in _DENY_EXACT if not name.startswith("NEXUS_")}
    for cls in _groups():
        prefix = str(cls.model_config.get("env_prefix", ""))
        if prefix.startswith(("KEY_POLICY_", "NEXUS_UNBOUND")):
            continue
        for field in cls.model_fields:
            name = f"{prefix}{field}".upper()
            assert (name in TOML_ALLOWED) != (name in not_settings), name


def test_allowed_names_never_hit_the_denylist() -> None:
    assert [n for n in sorted(TOML_ALLOWED) if _denied(n)] == []


def test_allowed_bare_keys_never_hit_the_denylist() -> None:
    """The guard also checks the bare key (without the table), so every allowed one must pass."""
    data = tomllib.loads(REPO_TOML.read_text())
    bare = {key for body in data.values() for key in body}
    assert [k for k in sorted(bare) if _denied(k)] == []


# ------------------------------------------------------------------ missing file
def test_explicit_missing_file_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_CONFIG_FILE", "does-not-exist.toml")
    with pytest.raises(ConfigFileError, match=r"does-not-exist\.toml"):
        SpreadSettings()


def test_default_missing_file_warns_and_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_CONFIG_FILE", raising=False)
    with capture_logs() as logs:
        assert SpreadSettings().min_net_profit_usd == Decimal(5)
    assert any(e["event"] == "config_file_missing" for e in logs)


def test_default_missing_file_refused_in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_CONFIG_FILE", raising=False)
    monkeypatch.setenv("NEXUS_RUNTIME", "container")
    with pytest.raises(ConfigFileError, match="not found"):
        SpreadSettings()


# ------------------------------------------------------------------ guard
@pytest.mark.parametrize(
    ("body", "key"),
    [
        (f'[telegram]\nbot_token = "{SECRET_VALUE}"\n', "bot_token"),
        (f'[telegram]\nchat_id = "{SECRET_VALUE}"\n', "chat_id"),
        (f'[telegram]\napi_base_url = "https://{SECRET_VALUE}.example"\n', "api_base_url"),
        (f'[postgres]\npassword = "{SECRET_VALUE}"\n', "password"),
        (f'[redis]\nurl = "{SECRET_VALUE}"\n', "url"),
        (f'[celery]\nbroker_url = "{SECRET_VALUE}"\n', "broker_url"),
        (f'[celery]\nresult_backend = "{SECRET_VALUE}"\n', "result_backend"),
        (f'[nexus]\nruntime = "{SECRET_VALUE}"\n', "runtime"),
        (f'[nexus]\nworker_role = "{SECRET_VALUE}"\n', "worker_role"),
        (f'[nexus]\nconfig_file = "{SECRET_VALUE}"\n', "config_file"),
        (f'[mexc]\napi_key = "{SECRET_VALUE}"\n', "api_key"),
        (f'[credentials]\nmexc_api_secret = "{SECRET_VALUE}"\n', "mexc_api_secret"),
        (f'[okx]\napi_passphrase = "{SECRET_VALUE}"\n', "api_passphrase"),
        ("[key_policy]\nkucoin_ip_attested = true\n", "kucoin_ip_attested"),
        ("[key_policy]\ngateio_permissions_attested = true\n", "gateio_permissions_attested"),
        ("[key_policy]\nip_binding_waived = true\n", "ip_binding_waived"),
        (f'[spread]\nsome_dsn = "{SECRET_VALUE}"\n', "some_dsn"),
    ],
)
def test_denylisted_key_refused_without_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, key: str
) -> None:
    path = _write(tmp_path, body, monkeypatch)
    with pytest.raises(ConfigFileError) as err:
        SpreadSettings()
    message = str(err.value)
    assert key in message
    assert str(path) in message
    assert "secret/env-only" in message
    assert SECRET_VALUE not in message


def test_unknown_key_and_table_refused_with_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\ntypo_key = 1\n", monkeypatch)
    with pytest.raises(ConfigFileError, match=r"cfg\.toml:3: \[spread\] typo_key: unknown key"):
        SpreadSettings()
    _write(tmp_path, "[nonsense]\nx = 1\n", monkeypatch)
    with pytest.raises(ConfigFileError, match="unknown key"):
        LoggingSettings()


def test_top_level_scalar_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "spread_min_net_profit_usd = 9\n", monkeypatch)
    with pytest.raises(ConfigFileError, match="outside a table"):
        SpreadSettings()


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://user:hunter2hunter2@db:5432/nexus",
        "redis://:topsecretpw@cache:6379/0",
        "123456789:AAH-abcdefghijklmnopqrstuvwxyz0123",
    ],
)
def test_credential_shaped_value_refused_without_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _write(tmp_path, f'[postgres]\nhost = "{value}"\n', monkeypatch)
    with pytest.raises(ConfigFileError) as err:
        DatabaseSettings(password=PW)  # type: ignore[arg-type]
    message = str(err.value)
    assert "host" in message
    assert "credential" in message
    assert value not in message
    assert "hunter2" not in message
    assert "topsecretpw" not in message


def test_credential_value_inside_list_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, '[scanner]\nsymbols_whitelist = ["x://u:pw12345@h"]\n', monkeypatch)
    with pytest.raises(ConfigFileError, match="symbols_whitelist"):
        SpreadSettings()


def test_parse_error_reports_position_but_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What happens when NEXUS_CONFIG_FILE mistakenly points at a .env file.
    body = f"TELEGRAM_BOT_TOKEN={SECRET_VALUE}\nPOSTGRES_PASSWORD={SECRET_VALUE}\n"
    _write(tmp_path, body, monkeypatch)
    with pytest.raises(ConfigFileError) as err:
        SpreadSettings()
    message = str(err.value)
    assert "line 1" in message
    assert SECRET_VALUE not in message
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__


def test_non_utf8_file_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "cfg.toml"
    path.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(path))
    with pytest.raises(ConfigFileError, match="not readable"):
        SpreadSettings()


def test_guard_runs_for_every_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, f'[postgres]\npassword = "{SECRET_VALUE}"\n', monkeypatch)
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)
    with pytest.raises(ConfigFileError):
        MigratorSettings.load()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567:" + "a" * 30)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with pytest.raises(ConfigFileError):
        AlertsWorkerSettings.load()


def test_denylist_exact_names_are_all_covered() -> None:
    assert all(_denied(name) for name in _DENY_EXACT)


# ------------------------------------------------------------------ provenance & hash
def test_env_overrides_listed_by_name_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_USD", "11")
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)  # secret: never listed
    monkeypatch.setenv("SPREAD_MAX_BOOK_SKEW_MS", "")  # empty: not an override
    Path(".env").write_text("LOG_LEVEL=DEBUG\nTELEGRAM_BOT_TOKEN=x\n")
    assert env_overridden_names() == ["LOG_LEVEL", "SPREAD_MIN_NET_PROFIT_USD"]


def test_dotenv_not_listed_in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("LOG_LEVEL=DEBUG\n")
    monkeypatch.setenv("NEXUS_RUNTIME", "container")
    assert env_overridden_names() == []


def test_startup_event_has_names_hash_and_no_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_USD", "11")
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)
    with capture_logs() as logs:
        log_settings_provenance("scanner")
    (event,) = [e for e in logs if e["event"] == "settings_loaded"]
    assert event["env_overrides"] == ["SPREAD_MIN_NET_PROFIT_USD"]
    assert event["config_file"] == str(path)
    assert len(event["settings_hash"]) == 64
    assert PW not in repr(event)


def test_hash_changes_with_settings_and_ignores_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = settings_hash()
    _write(tmp_path, "[spread]\nmin_net_profit_usd = 9\n", monkeypatch)
    from_toml = settings_hash()
    assert from_toml != base
    _write(tmp_path, "", monkeypatch)
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_USD", "9")
    assert settings_hash() == from_toml  # same effective value, other source


def test_hash_excludes_secrets_and_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    base = settings_hash()
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567:" + "b" * 30)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("REDIS_URL", "redis://:pw-pw-pw-pw@h:6379/0")
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    monkeypatch.setenv("KEY_POLICY_KUCOIN_IP_ATTESTED", "true")
    assert settings_hash() == base


def test_hash_is_stable_across_role_contexts() -> None:
    assert settings_hash() == settings_hash()


# ------------------------------------------------------------------ R2: merged test-DB check
def test_merged_db_name_is_what_the_integration_guard_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The repo file says db = "nexus": without POSTGRES_DB=nexus_test the guard must refuse."""
    monkeypatch.setenv("NEXUS_CONFIG_FILE", str(REPO_TOML))
    monkeypatch.setenv("POSTGRES_PASSWORD", PW)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    merged = DatabaseSettings()
    assert merged.db == "nexus"
    with pytest.raises(UnsafeDatabaseError):
        assert_test_database(merged.db)
    monkeypatch.setenv("POSTGRES_DB", "nexus_test")
    assert_test_database(DatabaseSettings().db)


# ------------------------------------------------------------------ local.toml overlay
def test_local_overlay_wins_per_key_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, '[alert]\nlanguage = "en"\nmax_per_hour = 11\n', monkeypatch)
    (tmp_path / "local.toml").write_text('[alert]\nlanguage = "ru"\n')
    settings = AlertPolicySettings()
    assert settings.language == "ru"
    assert settings.max_per_hour == 11


def test_local_overlay_is_guarded_like_the_main_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, '[alert]\nlanguage = "en"\n', monkeypatch)
    (tmp_path / "local.toml").write_text('[telegram]\nbot_token = "x"\n')
    with pytest.raises(ConfigFileError, match=r"local\.toml"):
        AlertPolicySettings()


def test_env_still_beats_the_local_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, '[alert]\nlanguage = "en"\n', monkeypatch)
    (tmp_path / "local.toml").write_text('[alert]\nlanguage = "ru"\n')
    monkeypatch.setenv("ALERT_LANGUAGE", "en")
    assert AlertPolicySettings().language == "en"
