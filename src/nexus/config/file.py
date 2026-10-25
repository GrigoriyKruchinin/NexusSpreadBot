"""Committed settings file ``config/nexus.toml``: loader and fail-closed guard (A7).

Priority: init kwargs > environment > ``.env`` (local only) > TOML file > code default.

The file holds SETTING-class values only (see ``docs/audit/security-config-split-A7.md``).
Secrets and ENV-ONLY values (tokens, passwords, key-policy attestations, the Telegram API host,
runtime plumbing) must come from the environment. The guard therefore refuses to start when the
file contains anything outside :data:`TOML_ALLOWED`, any denylisted name, or a credential-shaped
value. Error messages name the file, the key and the line; they never contain a value.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

import structlog
from dotenv import dotenv_values
from pydantic_settings import (
    InitSettingsSource,
    PydanticBaseSettingsSource,
    TomlConfigSettingsSource,
)

log = structlog.get_logger(__name__)

CONFIG_FILE_ENV = "NEXUS_CONFIG_FILE"
"""Environment variable that points at the settings file (ENV-ONLY: cannot live in the file)."""
DEFAULT_CONFIG_FILE = "config/nexus.toml"
"""Used when :data:`CONFIG_FILE_ENV` is unset; resolved against the working directory."""

#: Full env-style names (``<TABLE>_<KEY>``) of every SETTING-class field, i.e. the only keys the
#: file may contain. A consistency test ties this list to the settings groups.
TOML_ALLOWED: frozenset[str] = frozenset(
    {
        "TELEGRAM_DISABLE_NOTIFICATION",
        "TELEGRAM_ALERT_MAX_AGE_S",
        "TELEGRAM_EVENT_MAX_AGE_S",
        "TELEGRAM_REQUEST_TIMEOUT_S",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_POOL_SIZE",
        "POSTGRES_MAX_OVERFLOW",
        "POSTGRES_ECHO",
        "REDIS_SOCKET_TIMEOUT_S",
        "CELERY_TIMEZONE",
        "LOG_LEVEL",
        "LOG_JSON_FORMAT",
        "EXCHANGES_ENABLED",
        "EXCHANGES_REQUEST_TIMEOUT_MS",
        "CONDITIONAL_VENUES",
        "SCANNER_QUOTE_ASSETS",
        "SCANNER_SYMBOLS_WHITELIST",
        "SCANNER_SYMBOLS_BLACKLIST",
        "SCANNER_MIN_QUOTE_VOLUME_USD",
        "SCANNER_TICKER_INTERVAL_S",
        "SCANNER_METADATA_REFRESH_S",
        "SCANNER_ORDERBOOK_DEPTH",
        "SCANNER_MAX_CANDIDATES_PER_SWEEP",
        "SCANNER_MAX_CONCURRENT_REQUESTS_PER_EXCHANGE",
        "SCANNER_SNAPSHOT_TOP_K",
        "SCANNER_HEARTBEAT_TTL_S",
        "SCANNER_EXCHANGE_DOWN_AFTER_FAILURES",
        "SCANNER_RATE_LIMIT_BACKOFF_S",
        "SCANNER_WS_ENABLED",
        "SCANNER_WS_MAX_STREAMS",
        "SCANNER_WS_HOT_TTL_S",
        "SCANNER_LATENCY_CHECK_MS",
        "SPREAD_MIN_NET_PROFIT_PCT",
        "SPREAD_MIN_NET_PROFIT_USD",
        "SPREAD_REFERENCE_NOTIONAL_USD",
        "SPREAD_MAX_ORDERBOOK_AGE_MS",
        "SPREAD_MAX_BOOK_SKEW_MS",
        "SPREAD_MAX_GROSS_SPREAD_PCT",
        "SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT",
        "SPREAD_DEFAULT_TAKER_FEE_PCT",
        "SPREAD_INCLUDE_TRANSFER_COST",
        "SPREAD_TRANSFER_TAX_PCT",
        "SPREAD_REQUIRE_VERIFIED_TRANSFER",
        "SPREAD_ALERT_COOLDOWN_S",
        "ALERT_UPDATE_MIN_CHANGE_PCT",
        "ALERT_UPDATE_MIN_INTERVAL_S",
        "ALERT_MAX_PER_HOUR",
        "ALERT_SEND_MIN_INTERVAL_S",
        "ALERT_SEND_MAX_PER_MINUTE",
        "ALERT_SENDING_STALE_S",
        "ALERT_LANGUAGE",
        "EPISODE_CLOSE_GAP_S",
        "QUARANTINE_PERSIST_MIN",
        "QUARANTINE_TTL_H",
        "QUARANTINE_WINDOW_H",
        "QUARANTINE_MAX_EPISODES",
        "MAINTENANCE_SNAPSHOT_RETENTION_DAYS",
        "MAINTENANCE_EVALUATION_RETENTION_DAYS",
        "MAINTENANCE_EPISODE_RETENTION_DAYS",
        "MAINTENANCE_CLEANUP_INTERVAL_S",
        "DIGEST_ENABLED",
        "DIGEST_TIME",
        "DIGEST_TZ",
        "WATCHDOG_ENABLED",
        "WATCHDOG_INTERVAL_S",
        "WATCHDOG_SCANNER_STALE_MIN",
        "WATCHDOG_BACKUP_STATUS_PATH",
        "WATCHDOG_BACKUP_MAX_AGE_H",
    }
)

_DENY_EXACT: frozenset[str] = frozenset(
    {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_API_BASE_URL",
        "POSTGRES_PASSWORD",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "NEXUS_RUNTIME",
        "NEXUS_WORKER_ROLE",
        "NEXUS_CONFIG_FILE",
    }
)
_DENY_PREFIX = ("KEY_POLICY_",)
_DENY_RE = re.compile(
    r"(_API_(KEY|SECRET|PASSPHRASE)$|PASSWORD|PASSWD|SECRET|TOKEN|PASSPHRASE|PRIVATE_KEY"
    r"|CREDENTIAL|DSN|_URL$|_ATTESTED$)",
    re.IGNORECASE,
)
_CRED_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]*:[^/\s@]+@", re.IGNORECASE)
_TG_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")
_PARSE_POS_RE = re.compile(r"line (\d+), column (\d+)")

REASON_DENIED = "secret/env-only key not allowed in TOML"
REASON_UNKNOWN = "unknown key"
REASON_VALUE = "credential-bearing or token-shaped value not allowed"
REASON_NOT_TABLE = "key outside a table"


class ConfigFileError(RuntimeError):
    """The settings file is missing, unparsable or violates the guard (startup is refused).

    The message names file, key and line, never a value or a snippet of the file.
    """


def config_file_path() -> tuple[Path, bool]:
    """Return ``(path, explicit)``; ``explicit`` is true when ``NEXUS_CONFIG_FILE`` is set."""
    raw = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if raw:
        return Path(raw).expanduser(), True
    return Path(DEFAULT_CONFIG_FILE), False


def _is_container() -> bool:
    return os.environ.get("NEXUS_RUNTIME", "").strip().lower() == "container"


def _denied(name: str) -> bool:
    upper = name.upper()
    return upper in _DENY_EXACT or upper.startswith(_DENY_PREFIX) or bool(_DENY_RE.search(upper))


def _key_line(text: str, table: str, key: str) -> int | None:
    """Best-effort 1-based line of ``key`` inside ``[table]`` (None when not found)."""
    current = "<top level>"
    key_re = re.compile(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=")
    for number, line in enumerate(text.splitlines(), start=1):
        header = re.match(r"^\s*\[([^\[\]]+)\]", line)
        if header:
            current = header.group(1).strip()
            continue
        if current == table and key_re.match(line):
            return number
    return None


def _value_is_credential(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_CRED_URL_RE.search(value) or _TG_TOKEN_RE.search(value))
    if isinstance(value, dict):
        return any(_value_is_credential(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_value_is_credential(v) for v in value)
    return False


_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
UNPRINTABLE_NAME = "<unprintable key>"


def _printable(name: str) -> str:
    """Echo a key/table name only when it looks like an ordinary identifier (never a secret)."""
    if _SAFE_NAME_RE.fullmatch(name) and not _value_is_credential(name):
        return name
    return UNPRINTABLE_NAME


def _refuse(path: Path, table: str, key: str, line: int | None, reason: str) -> ConfigFileError:
    where = f"{path}:{line}" if line is not None else str(path)
    return ConfigFileError(f"{where}: [{_printable(table)}] {_printable(key)}: {reason}")


def validate_config(path: Path, data: dict[str, Any], text: str = "") -> None:
    """Fail closed on any key or value the file must not contain (see module docstring)."""
    for table, body in data.items():
        if not isinstance(body, dict):
            raise _refuse(
                path, "<top level>", table, _key_line(text, "<top level>", table), REASON_NOT_TABLE
            )
        for key, value in body.items():
            name = f"{table}_{key}".upper()
            line = _key_line(text, table, key)
            if _denied(name) or _denied(key):
                raise _refuse(path, table, key, line, REASON_DENIED)
            if name not in TOML_ALLOWED:
                raise _refuse(path, table, key, line, REASON_UNKNOWN)
            if _value_is_credential(value):
                raise _refuse(path, table, key, line, REASON_VALUE)


def present_env_names() -> set[str]:
    """Upper-case names set (non-empty) in the process env or, outside containers, in ``.env``.

    Names only: values are never kept. These are exactly the variables that win over the TOML file
    (``env_ignore_empty`` makes an empty value count as unset).
    """
    present = {k.upper() for k, v in os.environ.items() if v.strip()}
    if not _is_container() and Path(".env").is_file():
        present |= {k.upper() for k, v in dotenv_values(".env").items() if v and v.strip()}
    return present


def read_config_tables() -> dict[str, dict[str, Any]]:
    """Read and validate the settings file; ``{}`` when the default file is absent locally.

    Missing file: ``NEXUS_CONFIG_FILE`` set -> refuse; default path missing -> refuse inside
    containers (``NEXUS_RUNTIME=container``, reproducible runs), WARNING + code defaults locally.
    """
    path, explicit = config_file_path()
    if not path.is_file():
        if explicit or _is_container():
            raise ConfigFileError(f"{path}: settings file not found")
        log.warning("config_file_missing", path=str(path), effect="code defaults are used")
        return {}
    try:
        text = path.read_bytes().decode("utf-8")
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        match = _PARSE_POS_RE.search(str(exc))
        where = f" at line {match.group(1)}, column {match.group(2)}" if match else ""
        raise ConfigFileError(f"{path}: TOML parse error{where}") from None
    except (UnicodeDecodeError, OSError):
        raise ConfigFileError(f"{path}: file is not readable UTF-8 text") from None
    validate_config(path, data, text)
    return data


class NexusTomlSource(TomlConfigSettingsSource):
    """TOML source for one settings group: the table named after its ``env_prefix``.

    ``env_prefix="SPREAD_"`` reads ``[spread]``; keys are the field names. The whole file is
    guarded on every load, whichever group asks.
    """

    def __init__(self, settings_cls: type[Any]) -> None:
        tables = read_config_tables()
        prefix = str(settings_cls.model_config.get("env_prefix", "")).rstrip("_").lower()
        table = tables.get(prefix, {}) if prefix else {}
        # Env replaces the file per key. Without this, pydantic-settings deep-merges dict values
        # across sources (an env dict could never remove a key the file defines).
        overridden = present_env_names()
        table = {k: v for k, v in table.items() if f"{prefix}_{k}".upper() not in overridden}
        InitSettingsSource.__init__(self, settings_cls, table)


def toml_source(settings_cls: type[Any]) -> PydanticBaseSettingsSource:
    """Build the guarded TOML source for ``settings_cls``."""
    return NexusTomlSource(settings_cls)
