"""Where the effective settings came from, and a hash of them (A7 Scope 5, risk R3).

* :func:`env_overridden_names` lists SETTING names (never values) whose effective value comes from
  the environment or ``.env`` instead of ``config/nexus.toml``: a stale local ``.env`` would
  otherwise silently override the versioned file.
* :func:`settings_hash` hashes the effective value of every SETTING field (typed and normalized,
  after env > TOML > default merge; Decimals normalized; deployment plumbing POSTGRES_/REDIS_/LOG_
  excluded). SECRET and ENV-ONLY fields are excluded entirely: not even a
  hash of a credential is derived. It is independent of the service role, so every container of
  one run logs the same value. It is separate from the paper run ``config_hash`` of B15 (which
  covers the derived paper/estimator parameters of one portfolio) and does not change it.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import structlog
from dotenv import dotenv_values
from pydantic import SecretStr

from nexus.config.base import NexusBaseSettings
from nexus.config.file import (
    TOML_ALLOWED,
    config_file_path,
    present_env_names,
    read_config_tables,
)
from nexus.config.groups import (
    AlertPolicySettings,
    CelerySettings,
    ConditionalVenuesSettings,
    DatabaseSettings,
    DigestSettings,
    EpisodeSettings,
    ExchangesSettings,
    LoggingSettings,
    MaintenanceSettings,
    PaperHedgedSettings,
    PaperSettings,
    QuarantineSettings,
    RedisSettings,
    ScannerSettings,
    SpreadSettings,
    TelegramSettings,
)

log = structlog.get_logger(__name__)

_DUMMY_DB_PASSWORD = "x" * 12  # placeholder so the group validates; the field is never hashed
_DUMMY_BOT_TOKEN = "0:" + "a" * 20  # placeholder, never hashed


def _prefix(cls: type[NexusBaseSettings]) -> str:
    return str(cls.model_config.get("env_prefix", ""))


def env_overridden_names() -> list[str]:
    """Sorted SETTING names set (non-empty) in the process env or, locally, in ``.env``."""
    return sorted(TOML_ALLOWED & present_env_names())


def dotenv_setting_names() -> list[str]:
    """Sorted SETTING names with a non-empty value in ``.env`` (names only, values never kept).

    In the docker stack these lines are ignored (containers do not read ``.env``); on the host
    they override ``config/nexus.toml``. Either way the user should move them into the file.
    """
    path = Path(".env")
    if not path.is_file():
        return []
    present = {k.upper() for k, v in dotenv_values(path).items() if v and v.strip()}
    return sorted(TOML_ALLOWED & present)


def main() -> int:
    """Host-side helper (``make check-env-settings``): print SETTING names found in ``.env``."""
    names = dotenv_setting_names()
    if names:
        print(  # noqa: T201 - CLI output, names only
            "WARNING: .env contains setting lines (names only, values not shown):\n  "
            + "\n  ".join(names)
            + "\nDocker containers IGNORE them; host runs let them override config/nexus.toml.\n"
            "Move any non-default value into config/nexus.toml and delete the line from .env."
        )
    return 0


#: Deployment plumbing (where/how the services run), not the strategy: excluded from the hash so a
#: host CLI run and the container stack hash the same strategy identically.
_HASH_EXCLUDED_PREFIXES = ("POSTGRES_", "REDIS_", "LOG_")


def _normalize(value: object) -> object:
    """Spelling-independent form: ``20``, ``20.0`` and ``2E+1`` all become ``"20"``."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    return value


def settings_hash() -> str:
    """SHA-256 over the effective, typed value of every SETTING field (sorted JSON)."""
    groups: list[NexusBaseSettings] = [
        TelegramSettings(bot_token=SecretStr(_DUMMY_BOT_TOKEN), chat_id="0"),
        DatabaseSettings(password=SecretStr(_DUMMY_DB_PASSWORD)),
        RedisSettings(),
        CelerySettings(),
        LoggingSettings(),
        ExchangesSettings(),
        ConditionalVenuesSettings(),
        ScannerSettings(),
        SpreadSettings(),
        AlertPolicySettings(),
        EpisodeSettings(),
        QuarantineSettings(),
        PaperSettings(),
        PaperHedgedSettings(),
        MaintenanceSettings(),
        DigestSettings(),
    ]
    payload: dict[str, object] = {}
    for group in groups:
        for field, value in group.model_dump().items():
            name = f"{_prefix(type(group))}{field}".upper()
            if name in TOML_ALLOWED and not name.startswith(_HASH_EXCLUDED_PREFIXES):
                payload[name] = _normalize(value)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def log_settings_provenance(service: str) -> None:
    """Log (once per process start) the settings file, run-settings hash and env overrides."""
    path, _ = config_file_path()
    read_config_tables()  # guard again so a missing/bad file is refused before the log line
    log.info(
        "settings_loaded",
        service=service,
        config_file=str(path),
        settings_hash=settings_hash(),
        env_overrides=env_overridden_names(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
