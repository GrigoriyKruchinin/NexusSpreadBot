"""Guard: .env.example and the env variables the code reads must stay in sync (T6, A7).

The expected set is DERIVED from the settings classes (no hand-kept list): SECRET and ENV-ONLY
fields only, since every tunable lives in config/nexus.toml and a setting line in .env.example
would silently override the versioned file for anyone who copies the template.
"""

import re
from pathlib import Path

from nexus.config.file import TOML_ALLOWED
from nexus.config.groups import (
    CORE_EXCHANGES,
    CelerySettings,
    DatabaseSettings,
    ExchangeCredentials,
    KeyPolicySettings,
    RedisSettings,
    TelegramSettings,
)

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

#: Venues whose API needs a passphrase in addition to key and secret.
_PASSPHRASE_VENUES = {"okx", "kucoin"}


def _env(prefix: str, field: str) -> str:
    return f"{prefix}{field}".upper()


def _expected_names() -> set[str]:
    names = {
        _env("TELEGRAM_", "bot_token"),
        _env("TELEGRAM_", "chat_id"),
        _env("POSTGRES_", "password"),
        _env("REDIS_", "url"),
        _env("CELERY_", "broker_url"),
    }
    # Guard the literal names above against field renames in the settings classes.
    assert {"bot_token", "chat_id"} <= set(TelegramSettings.model_fields)
    assert "password" in DatabaseSettings.model_fields
    assert "url" in RedisSettings.model_fields
    assert "broker_url" in CelerySettings.model_fields
    names |= {_env("KEY_POLICY_", f) for f in KeyPolicySettings.model_fields}
    cred_fields = set(ExchangeCredentials.model_fields)
    assert {"api_key", "api_secret", "api_passphrase"} == cred_fields
    for venue in CORE_EXCHANGES:
        names |= {f"{venue.upper()}_API_KEY", f"{venue.upper()}_API_SECRET"}
        if venue in _PASSPHRASE_VENUES:
            names.add(f"{venue.upper()}_API_PASSPHRASE")
    return names


def _documented_keys() -> set[str]:
    text = ENV_EXAMPLE.read_text()
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_no_setting_in_env_example() -> None:
    assert not _documented_keys() & TOML_ALLOWED


def test_env_example_matches_settings_read_by_code() -> None:
    documented, expected = _documented_keys(), _expected_names()
    assert documented - expected == set(), "in .env.example but not read by the code"
    assert expected - documented == set(), "read by the code but missing in .env.example"


def test_no_paper_or_ht_variables() -> None:
    assert not any(k.startswith(("PAPER_", "HT_")) for k in _documented_keys())


def test_env_example_has_no_values_that_look_like_secrets() -> None:
    values = re.findall(r"^[A-Z][A-Z0-9_]*=(.*)$", ENV_EXAMPLE.read_text(), flags=re.MULTILINE)
    assert not [v for v in values if re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", v)]
    # Only booleans, redis URLs without credentials, or empty values are allowed as defaults.
    assert all(v in {"", "false"} or re.fullmatch(r"redis://localhost:\d+/\d", v) for v in values)


def test_required_section_comes_first_and_keys_are_documented() -> None:
    text = ENV_EXAMPLE.read_text()
    assert text.index("# 1. REQUIRED") < text.index("# 2. OPTIONAL") < text.index("# 3. ADVANCED")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "POSTGRES_PASSWORD"):
        assert text.index(name + "=") < text.index("# 2. OPTIONAL")
