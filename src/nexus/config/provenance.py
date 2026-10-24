"""Where the effective settings came from, and a hash of them (A7 Scope 5, risk R3).

* :func:`env_overridden_names` lists SETTING names (never values) whose effective value comes from
  the environment or ``.env`` instead of ``config/nexus.toml``: a stale local ``.env`` would
  otherwise silently override the versioned file.
* :func:`settings_hash` hashes the effective value of every SETTING field (typed and normalized,
  after env > TOML > default merge). SECRET and ENV-ONLY fields are excluded entirely: not even a
  hash of a credential is derived. It is independent of the service role, so every container of
  one run logs the same value. It is separate from the paper run ``config_hash`` of B15 (which
  covers the derived paper/estimator parameters of one portfolio) and does not change it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import structlog
from dotenv import dotenv_values
from pydantic import SecretStr

from nexus.config.base import RUNTIME_ENV_VAR, NexusBaseSettings
from nexus.config.file import TOML_ALLOWED, config_file_path, read_config_tables
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
    present = {k.upper() for k, v in os.environ.items() if v.strip()}
    if (
        os.environ.get(RUNTIME_ENV_VAR, "").strip().lower() != "container"
        and Path(".env").is_file()
    ):
        present |= {k.upper() for k, v in dotenv_values(".env").items() if v and v.strip()}
    return sorted(TOML_ALLOWED & present)


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
        MaintenanceSettings(),
        DigestSettings(),
    ]
    payload: dict[str, object] = {}
    for group in groups:
        dumped = group.model_dump(mode="json")
        for field, value in dumped.items():
            name = f"{_prefix(type(group))}{field}".upper()
            if name in TOML_ALLOWED:
                payload[name] = value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
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
