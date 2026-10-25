import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.config import (
    CORE_EXCHANGES,
    AlertsWorkerSettings,
    ExchangeCredentials,
    ExchangesSettings,
    MigratorSettings,
    ScannerRoleSettings,
    ScannerSettings,
    SchedulerSettings,
    SpreadSettings,
    TelegramSettings,
)

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "nexus.toml"
VALID_TOKEN = "123456789:AAHabcdefghijklmnopqrstuvwxyz012345"
DB_PASSWORD = "correct-horse-battery-staple"


def test_spread_defaults_match_confirmed_product_decisions() -> None:
    spread = SpreadSettings()
    assert spread.min_net_profit_pct == Decimal("0.3")
    assert spread.min_net_profit_usd == Decimal(5)
    assert spread.reference_notional_usd == Decimal(1000)


def test_spread_values_are_decimal_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_PCT", "0.15")
    assert SpreadSettings().min_net_profit_pct == Decimal("0.15")


def test_exchanges_enabled_accepts_csv_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGES_ENABLED", "Bybit, okx")
    assert ExchangesSettings().enabled == ("bybit", "okx")
    monkeypatch.setenv("EXCHANGES_ENABLED", '["binance","kucoin"]')
    assert ExchangesSettings().enabled == ("binance", "kucoin")


def test_exchanges_default_is_core_exchanges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXCHANGES_ENABLED", raising=False)
    assert ExchangesSettings().enabled == CORE_EXCHANGES
    assert set(CORE_EXCHANGES) == {"binance", "bybit", "gateio", "kucoin", "okx"}


def test_exchanges_empty_env_falls_back_to_core(monkeypatch: pytest.MonkeyPatch) -> None:
    # docker-compose.local.yml passes an unset EXCHANGES_ENABLED as "".
    monkeypatch.setenv("EXCHANGES_ENABLED", "")
    assert ExchangesSettings().enabled == CORE_EXCHANGES


def test_exchanges_extension_venues_loadable_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXCHANGES_ENABLED", "binance,bybit,mexc,bitget")
    assert ExchangesSettings().enabled == ("binance", "bybit", "mexc", "bitget")


def test_config_file_exchanges_in_sync_with_core() -> None:
    data = tomllib.loads(CONFIG_FILE.read_text())
    assert tuple(data["exchanges"]["enabled"]) == CORE_EXCHANGES


@pytest.mark.parametrize("value", ["bybit", "bybit,bybit", "by-bit,okx"])
def test_exchanges_enabled_rejects_invalid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("EXCHANGES_ENABLED", value)
    with pytest.raises(ValidationError):
        ExchangesSettings()


def test_exchange_credentials_bound_to_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKX_API_KEY", "k")
    monkeypatch.setenv("OKX_API_SECRET", "s")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "p")
    okx = ExchangeCredentials.for_exchange("okx")
    bybit = ExchangeCredentials.for_exchange("bybit")
    assert okx.is_configured
    assert okx.api_passphrase is not None
    assert okx.api_passphrase.get_secret_value() == "p"
    assert not bybit.is_configured


def test_exchange_credentials_empty_values_mean_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BYBIT_API_KEY", "")
    monkeypatch.setenv("BYBIT_API_SECRET", "  ")
    assert not ExchangeCredentials.for_exchange("bybit").is_configured


def test_exchange_credentials_key_without_secret_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    with pytest.raises(ValidationError):
        ExchangeCredentials.for_exchange("bybit")


def test_secrets_are_not_rendered_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "super-secret-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "super-secret-value")
    rendered = repr(ExchangeCredentials.for_exchange("binance"))
    assert "super-secret" not in rendered


def test_telegram_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")
    assert TelegramSettings().chat_id == "-1001234567890"
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-chat")
    with pytest.raises(ValidationError):
        TelegramSettings()


def test_telegram_rejects_malformed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "oops")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with pytest.raises(ValidationError):
        TelegramSettings()


def test_scanner_quote_assets_restricted_to_usd_stables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCANNER_QUOTE_ASSETS", "usdt,usdc")
    assert ScannerSettings().quote_assets == ("USDT", "USDC")
    monkeypatch.setenv("SCANNER_QUOTE_ASSETS", "BTC")
    with pytest.raises(ValidationError):
        ScannerSettings()


# --------------------------------------------------------------- role isolation


def test_migrator_needs_only_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    settings = MigratorSettings.load()
    assert settings.database.password.get_secret_value() == DB_PASSWORD
    assert set(MigratorSettings.model_fields) == {"database", "logging"}


def test_scheduler_has_no_secrets_groups() -> None:
    settings = SchedulerSettings.load()  # no env at all is enough
    assert set(SchedulerSettings.model_fields) == {
        "celery",
        "maintenance",
        "digest",
        "watchdog",
        "logging",
    }
    assert settings.maintenance.cleanup_interval_s > 0


def test_scanner_loads_without_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("EXCHANGES_ENABLED", "bybit,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "bybit")  # default (gateio) is not enabled here
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    monkeypatch.setenv("BYBIT_API_SECRET", "s")
    settings = ScannerRoleSettings.load()
    assert set(settings.credentials) == {"bybit", "okx"}
    assert settings.credentials["bybit"].is_configured
    assert "telegram" not in ScannerRoleSettings.model_fields


def test_alerts_worker_has_no_exchange_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    settings = AlertsWorkerSettings.load()
    assert settings.telegram.chat_id == "42"
    assert not {"credentials", "exchanges", "redis"} & set(AlertsWorkerSettings.model_fields)


def test_alerts_worker_requires_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    with pytest.raises(ValidationError):
        AlertsWorkerSettings.load()


def test_dotenv_file_is_read() -> None:
    # cwd is an isolated tmp dir (see conftest); write a .env there.
    from pathlib import Path

    Path(".env").write_text("SPREAD_MIN_NET_PROFIT_USD=7\nTELEGRAM_CHAT_ID=1\n")
    assert SpreadSettings().min_net_profit_usd == Decimal(7)


# --------------------------------------------------------------- audit regressions


@pytest.mark.parametrize(
    ("env", "secret"),
    [
        (
            {"TELEGRAM_BOT_TOKEN": "123456:SUPERSECRET_TOKEN with space", "TELEGRAM_CHAT_ID": "1"},
            "SUPERSECRET",
        ),
    ],
)
def test_validation_errors_do_not_leak_telegram_token(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], secret: str
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError) as exc_info:
        TelegramSettings()
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("present", ["BYBIT_API_SECRET", "BYBIT_API_KEY"])
def test_validation_errors_do_not_leak_exchange_secrets(
    monkeypatch: pytest.MonkeyPatch, present: str
) -> None:
    monkeypatch.setenv(present, "TOPSECRET_SIGNING_KEY")
    with pytest.raises(ValidationError) as exc_info:
        ExchangeCredentials.for_exchange("bybit")
    assert "TOPSECRET" not in str(exc_info.value)


def test_passphrase_without_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKX_API_PASSPHRASE", "p")
    with pytest.raises(ValidationError):
        ExchangeCredentials.for_exchange("okx")


def test_unbound_credentials_ignore_generic_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("API_SECRET", "s")
    assert not ExchangeCredentials().is_configured


def test_dotenv_ignored_in_container_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    Path(".env").write_text("SPREAD_MIN_NET_PROFIT_USD=7\n")
    Path("empty.toml").write_text("")
    monkeypatch.setenv("NEXUS_CONFIG_FILE", "empty.toml")
    monkeypatch.setenv("NEXUS_RUNTIME", "container")
    assert SpreadSettings().min_net_profit_usd == Decimal(5)


@pytest.mark.parametrize("password", ["", "   ", "short"])
def test_weak_database_password_rejected(monkeypatch: pytest.MonkeyPatch, password: str) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    with pytest.raises(ValidationError):
        MigratorSettings.load()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SPREAD_MAX_ORDERBOOK_AGE_MS", "86400000"),
        ("SPREAD_MAX_BOOK_SKEW_MS", "99999999"),
        ("SPREAD_DEFAULT_TAKER_FEE_PCT", "0"),
        ("SPREAD_MAX_GROSS_SPREAD_PCT", "0.1"),
        ("SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT", "0.2"),
        ("SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT", "25"),
    ],
)
def test_unsafe_spread_settings_rejected(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        SpreadSettings()


def test_skew_must_not_exceed_age(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPREAD_MAX_ORDERBOOK_AGE_MS", "2000")
    monkeypatch.setenv("SPREAD_MAX_BOOK_SKEW_MS", "3000")
    with pytest.raises(ValidationError):
        SpreadSettings()


def test_telegram_base_url_must_be_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_BASE_URL", "http://evil.example")
    with pytest.raises(ValidationError):
        TelegramSettings()


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCANNER_TICKER_INTERVAL_S", "")
    monkeypatch.setenv("SPREAD_MIN_NET_PROFIT_PCT", "")
    assert ScannerSettings().ticker_interval_s == 10.0
    assert SpreadSettings().min_net_profit_pct == Decimal("0.3")


def test_empty_required_value_is_still_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with pytest.raises(ValidationError):
        TelegramSettings()


def test_episode_gap_must_span_two_sweeps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "a-strong-password")
    assert ScannerRoleSettings.load().episodes.close_gap_s == 300
    assert ScannerRoleSettings.load().scanner.latency_check_ms == 2_000
    monkeypatch.setenv("SCANNER_TICKER_INTERVAL_S", "151")
    with pytest.raises(ValueError, match="EPISODE_CLOSE_GAP_S"):
        ScannerRoleSettings.load()
    monkeypatch.setenv("EPISODE_CLOSE_GAP_S", "302")
    assert ScannerRoleSettings.load().episodes.close_gap_s == 302


@pytest.mark.parametrize(
    ("env", "value"),
    [("DIGEST_TIME", "9:00"), ("DIGEST_TIME", "24:00"), ("DIGEST_TZ", "Mars/Olympus")],
)
def test_digest_settings_validation(monkeypatch: pytest.MonkeyPatch, env: str, value: str) -> None:
    from nexus.config.groups import DigestSettings

    monkeypatch.setenv(env, value)
    with pytest.raises(ValueError, match=env):
        DigestSettings()


def test_digest_settings_defaults() -> None:
    from nexus.config.groups import DigestSettings

    digest = DigestSettings()
    assert (digest.enabled, digest.hour, digest.minute, digest.tz) == (
        True,
        9,
        0,
        "Europe/Moscow",
    )


def test_transfer_taxes_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert SpreadSettings().transfer_tax_pct == {"LUNC": Decimal("1.5"), "USTC": Decimal("1.5")}
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"lunc": 2, "XYZ": "0.5"}')
    assert SpreadSettings().transfer_tax_pct == {"LUNC": Decimal(2), "XYZ": Decimal("0.5")}
    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"LUNC": 60}')
    with pytest.raises(ValueError, match="SPREAD_TRANSFER_TAX_PCT"):
        SpreadSettings()


def test_tax_assets_must_be_unique_and_window_must_cover_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.config.groups import QuarantineSettings

    monkeypatch.setenv("SPREAD_TRANSFER_TAX_PCT", '{"lunc": 1, "LUNC": 2}')
    with pytest.raises(ValueError, match="duplicate"):
        SpreadSettings()
    monkeypatch.setenv("QUARANTINE_PERSIST_MIN", "120")
    monkeypatch.setenv("QUARANTINE_WINDOW_H", "1")
    with pytest.raises(ValueError, match="QUARANTINE_PERSIST_MIN"):
        QuarantineSettings()


# --------------------------------------------------------------- conditional venues (B14)


def test_conditional_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.config import ConditionalVenuesSettings

    assert ConditionalVenuesSettings().venues == ("bybit", "gateio")
    monkeypatch.setenv("CONDITIONAL_VENUES", "okx")
    assert ConditionalVenuesSettings().venues == ("okx",)
    monkeypatch.setenv("CONDITIONAL_VENUES", '["Bybit"," KuCoin "]')
    assert ConditionalVenuesSettings().venues == ("bybit", "kucoin")  # lowercase, trimmed


def test_conditional_empty_env_falls_back_but_empty_list_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.config import ConditionalVenuesSettings

    monkeypatch.setenv("CONDITIONAL_VENUES", "")  # compose passes unset as ""
    assert ConditionalVenuesSettings().venues == ("bybit", "gateio")
    monkeypatch.setenv("CONDITIONAL_VENUES", "[]")
    assert ConditionalVenuesSettings().venues == ()


@pytest.mark.parametrize("value", ["bybit,bybit", "by-bit", "1bybit"])
def test_conditional_rejects_invalid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from nexus.config import ConditionalVenuesSettings

    monkeypatch.setenv("CONDITIONAL_VENUES", value)
    with pytest.raises(ValidationError):
        ConditionalVenuesSettings()


def test_scanner_rejects_conditional_venue_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("EXCHANGES_ENABLED", "binance,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "okx,bybit")
    with pytest.raises(ValidationError, match="bybit"):
        ScannerRoleSettings.load()
    monkeypatch.setenv("CONDITIONAL_VENUES", "okx")
    assert ScannerRoleSettings.load().conditional.venues == ("okx",)


def test_alerts_worker_loads_conditional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    assert AlertsWorkerSettings.load().conditional.venues == ("bybit", "gateio")


def test_config_file_conditional_matches_default() -> None:
    data = tomllib.loads(CONFIG_FILE.read_text())
    assert tuple(data["conditional"]["venues"]) == ("bybit", "gateio")


def _scanner_env(monkeypatch: pytest.MonkeyPatch, enabled: str) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("EXCHANGES_ENABLED", enabled)


def test_scanner_unset_conditional_follows_narrowed_enabled_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from structlog.testing import capture_logs

    _scanner_env(monkeypatch, "binance,bybit,okx")  # gateio not enabled, CONDITIONAL_VENUES unset
    with capture_logs() as logs:
        settings = ScannerRoleSettings.load()
    assert settings.conditional.venues == ("bybit",)
    [record] = [r for r in logs if r["event"] == "conditional_venues_defaulted"]
    assert record["log_level"] == "warning"
    assert record["default"] == ["bybit", "gateio"]
    assert record["effective"] == ["bybit"]


def test_scanner_unset_conditional_no_warning_when_all_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from structlog.testing import capture_logs

    _scanner_env(monkeypatch, "binance,bybit,gateio")
    with capture_logs() as logs:
        assert ScannerRoleSettings.load().conditional.venues == ("bybit", "gateio")
    assert not [r for r in logs if r["event"] == "conditional_venues_defaulted"]


def test_scanner_empty_conditional_env_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scanner_env(monkeypatch, "binance,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "")  # compose passes unset as ""
    assert ScannerRoleSettings.load().conditional.venues == ()


def test_scanner_explicit_conditional_unknown_venue_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from structlog.testing import capture_logs

    _scanner_env(monkeypatch, "binance,bybit,gateio")
    monkeypatch.setenv("CONDITIONAL_VENUES", "gate")  # typo of gateio
    with capture_logs() as logs, pytest.raises(ValidationError, match="gate"):
        ScannerRoleSettings.load()
    assert not [r for r in logs if r["event"] == "conditional_venues_defaulted"]
    monkeypatch.setenv("CONDITIONAL_VENUES", "bybit,okx")  # okx is not enabled
    with pytest.raises(ValidationError, match="okx"):
        ScannerRoleSettings.load()


def test_scanner_explicit_empty_list_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _scanner_env(monkeypatch, "binance,okx")
    monkeypatch.setenv("CONDITIONAL_VENUES", "[]")
    assert ScannerRoleSettings.load().conditional.venues == ()
