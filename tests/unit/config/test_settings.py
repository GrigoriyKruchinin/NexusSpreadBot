from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexus.config import (
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
    assert set(SchedulerSettings.model_fields) == {"celery", "maintenance", "logging"}
    assert settings.maintenance.cleanup_interval_s > 0


def test_scanner_loads_without_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", DB_PASSWORD)
    monkeypatch.setenv("EXCHANGES_ENABLED", "bybit,okx")
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
