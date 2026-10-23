"""Guard: every settings field must be documented in .env.example."""

import re
from pathlib import Path

from nexus.config import (
    CelerySettings,
    ConditionalVenuesSettings,
    DatabaseSettings,
    ExchangesSettings,
    LoggingSettings,
    MaintenanceSettings,
    RedisSettings,
    ScannerSettings,
    SpreadSettings,
    TelegramSettings,
)
from nexus.config.base import NexusBaseSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"

# Fields intentionally not exposed in .env.example (tuning knobs with safe defaults).
_UNDOCUMENTED = {
    "POSTGRES_POOL_SIZE",
    "POSTGRES_MAX_OVERFLOW",
    "POSTGRES_ECHO",
    "REDIS_SOCKET_TIMEOUT_S",
    "CELERY_RESULT_BACKEND",
    "TELEGRAM_API_BASE_URL",
    "TELEGRAM_REQUEST_TIMEOUT_S",
}

_GROUPS: tuple[type[NexusBaseSettings], ...] = (
    DatabaseSettings,
    RedisSettings,
    CelerySettings,
    TelegramSettings,
    LoggingSettings,
    ExchangesSettings,
    ConditionalVenuesSettings,
    ScannerSettings,
    SpreadSettings,
    MaintenanceSettings,
)


def _documented_keys() -> set[str]:
    text = ENV_EXAMPLE.read_text()
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_all_settings_fields_documented() -> None:
    documented = _documented_keys()
    missing = set()
    for group in _GROUPS:
        prefix = str(group.model_config.get("env_prefix", ""))
        for field in group.model_fields:
            key = f"{prefix}{field}".upper()
            if key not in documented and key not in _UNDOCUMENTED:
                missing.add(key)
    assert not missing, f".env.example is missing: {sorted(missing)}"


def test_credentials_documented_for_default_exchanges() -> None:
    documented = _documented_keys()
    for name in ExchangesSettings.model_fields["enabled"].default:
        assert f"{name.upper()}_API_KEY" in documented
        assert f"{name.upper()}_API_SECRET" in documented
