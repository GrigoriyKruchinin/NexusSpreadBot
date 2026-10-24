"""Guard: .env.example documents SECRET and ENV-ONLY variables only (A7).

Every tunable lives in config/nexus.toml; a setting in .env.example would silently override the
versioned file for anyone who copies the template.
"""

import re
from pathlib import Path

from nexus.config.file import TOML_ALLOWED
from nexus.config.groups import ExchangesSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

EXPECTED_SECRET_AND_ENV_ONLY = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "KEY_POLICY_KUCOIN_IP_ATTESTED",
    "KEY_POLICY_GATEIO_PERMISSIONS_ATTESTED",
    "KEY_POLICY_IP_BINDING_WAIVED",
}
_API_SUFFIXES = ("_API_KEY", "_API_SECRET", "_API_PASSPHRASE")


def _documented_keys() -> set[str]:
    text = ENV_EXAMPLE.read_text()
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_no_setting_in_env_example() -> None:
    assert not _documented_keys() & TOML_ALLOWED


def test_only_secret_and_env_only_documented() -> None:
    other = {k for k in _documented_keys() if not k.endswith(_API_SUFFIXES)}
    assert other == EXPECTED_SECRET_AND_ENV_ONLY


def test_credentials_documented_for_default_exchanges() -> None:
    documented = _documented_keys()
    for name in ExchangesSettings.model_fields["enabled"].default:
        assert f"{name.upper()}_API_KEY" in documented
        assert f"{name.upper()}_API_SECRET" in documented
