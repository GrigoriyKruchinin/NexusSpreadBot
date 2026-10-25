"""Domain-specific settings groups.

Every group reads only variables with its own prefix. Containers compose the groups they
need via the role loaders in :mod:`nexus.config.roles`; a group that is never instantiated
in a container never requires (or sees) its secrets.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from nexus.config.base import NexusBaseSettings, StrTuple

_EXCHANGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MIN_DB_PASSWORD_LENGTH = 12


class DatabaseSettings(NexusBaseSettings):
    """PostgreSQL connection settings (``POSTGRES_*``)."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = Field(default=5432, gt=0, lt=65536)
    db: str = "nexus"
    user: str = "nexus"
    password: SecretStr
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=5, ge=0)
    echo: bool = False

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().strip()) < _MIN_DB_PASSWORD_LENGTH:
            msg = f"POSTGRES_PASSWORD must be at least {_MIN_DB_PASSWORD_LENGTH} characters"
            raise ValueError(msg)
        return value


class RedisSettings(NexusBaseSettings):
    """Redis cache / coordination settings (``REDIS_*``)."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: SecretStr = SecretStr("redis://localhost:6379/0")
    socket_timeout_s: float = Field(default=5.0, gt=0)


class CelerySettings(NexusBaseSettings):
    """Celery broker settings (``CELERY_*``)."""

    model_config = SettingsConfigDict(env_prefix="CELERY_")

    broker_url: SecretStr = SecretStr("redis://localhost:6379/1")
    result_backend: SecretStr | None = None
    timezone: str = "UTC"


class TelegramSettings(NexusBaseSettings):
    """Telegram Bot API settings (``TELEGRAM_*``)."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr
    chat_id: str
    api_base_url: str = "https://api.telegram.org"
    request_timeout_s: float = Field(default=10.0, gt=0)
    disable_notification: bool = False
    alert_max_age_s: int = Field(default=30, ge=10, le=3_600)
    """Opportunity alerts older than this (queue backlog, retries) are dropped, not sent."""
    event_max_age_s: int = Field(default=300, ge=30, le=86_400)
    """System events (exchange down/recovered, start/stop) older than this are dropped."""

    @field_validator("chat_id")
    @classmethod
    def _validate_chat_id(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("@"):
            return value
        if not re.fullmatch(r"-?\d+", value):
            msg = "TELEGRAM_CHAT_ID must be a numeric id (e.g. -1001234567890) or @channel_name"
            raise ValueError(msg)
        return value

    @field_validator("api_base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        # The bot token travels in the URL path of every request.
        if not value.startswith("https://"):
            msg = "TELEGRAM_API_BASE_URL must use https://"
            raise ValueError(msg)
        return value.rstrip("/")

    @field_validator("bot_token")
    @classmethod
    def _validate_token(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", value.get_secret_value()):
            msg = "TELEGRAM_BOT_TOKEN has an invalid format (expected '<digits>:<token>')"
            raise ValueError(msg)
        return value


class LoggingSettings(NexusBaseSettings):
    """Logging settings (``LOG_*``)."""

    model_config = SettingsConfigDict(env_prefix="LOG_")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_format: bool = True


#: Core venues whose data counts towards the GO decision (ADR 0002, ADR 0004). bitget/mexc are
#: extension-only: their adapters stay registered, but they are enabled only via explicit config.
CORE_EXCHANGES: tuple[str, ...] = ("binance", "bybit", "gateio", "kucoin", "okx")


class ExchangesSettings(NexusBaseSettings):
    """Which exchanges are enabled and how to talk to them (``EXCHANGES_*``)."""

    model_config = SettingsConfigDict(env_prefix="EXCHANGES_")

    enabled: StrTuple = CORE_EXCHANGES
    request_timeout_ms: int = Field(default=10_000, ge=1_000, le=60_000)

    @field_validator("enabled")
    @classmethod
    def _validate_enabled(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(name.strip().lower() for name in value)
        for name in normalized:
            if not _EXCHANGE_NAME_RE.fullmatch(name):
                msg = f"invalid exchange name: {name!r}"
                raise ValueError(msg)
        if len(set(normalized)) != len(normalized):
            msg = "EXCHANGES_ENABLED contains duplicates"
            raise ValueError(msg)
        if len(normalized) < 2:  # arbitrage needs at least two venues
            msg = "at least two exchanges must be enabled"
            raise ValueError(msg)
        return normalized


#: Venues whose data is collected but where the user may not be able to trade now (vision GO-HOLD).
DEFAULT_CONDITIONAL_VENUES: tuple[str, ...] = ("bybit", "gateio")


class ConditionalVenuesSettings(NexusBaseSettings):
    """Conditional venues reported separately in every aggregate (``CONDITIONAL_VENUES``).

    The subset-of-enabled check lives on the scanner role settings, the only place that knows
    ``EXCHANGES_ENABLED``. An empty list (``[]``) means "no conditional venues".
    """

    model_config = SettingsConfigDict(env_prefix="CONDITIONAL_")

    venues: StrTuple = DEFAULT_CONDITIONAL_VENUES

    @field_validator("venues")
    @classmethod
    def _validate_venues(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(name.strip().lower() for name in value)
        for name in normalized:
            if not _EXCHANGE_NAME_RE.fullmatch(name):
                msg = f"invalid conditional venue name: {name!r}"
                raise ValueError(msg)
        if len(set(normalized)) != len(normalized):
            msg = "CONDITIONAL_VENUES contains duplicates"
            raise ValueError(msg)
        return normalized


class ExchangeCredentials(NexusBaseSettings):
    """Read-only API credentials of a single exchange (``<NAME>_API_*``).

    Instantiate via :meth:`for_exchange`, which binds the env prefix to the exchange name,
    e.g. ``BYBIT_API_KEY`` / ``BYBIT_API_SECRET`` / ``BYBIT_API_PASSPHRASE``. Direct
    construction reads an unused sentinel prefix and therefore yields empty credentials.
    Whether a passphrase is mandatory is validated by the exchange adapter.
    """

    model_config = SettingsConfigDict(env_prefix="NEXUS_UNBOUND_EXCHANGE_")

    api_key: SecretStr | None = None
    api_secret: SecretStr | None = None
    api_passphrase: SecretStr | None = None

    @classmethod
    def for_exchange(cls, name: str) -> ExchangeCredentials:
        """Load credentials for ``name`` from ``<NAME>_API_*`` variables."""
        return cls(_env_prefix=f"{name.upper()}_")

    @field_validator("api_key", "api_secret", "api_passphrase", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _key_and_secret_together(self) -> Self:
        if (self.api_key is None) != (self.api_secret is None):
            msg = "API key and API secret must be provided together"
            raise ValueError(msg)
        if self.api_passphrase is not None and self.api_key is None:
            msg = "API passphrase provided without API key/secret"
            raise ValueError(msg)
        return self

    @property
    def is_configured(self) -> bool:
        """True when a key/secret pair is present."""
        return self.api_key is not None


class KeyPolicySettings(NexusBaseSettings):
    """User attestations for key properties the venue API does not expose (``KEY_POLICY_*``).

    Non-secret booleans. A venue whose key cannot be fully introspected needs its flag set
    after the user verified the property by hand (U3 guide); otherwise startup is refused.
    """

    model_config = SettingsConfigDict(env_prefix="KEY_POLICY_")

    kucoin_ip_attested: bool = False
    """KuCoin's key info does not show the IP whitelist: the key is IP-restricted."""
    gateio_permissions_attested: bool = False
    """Gate.io has no per-key scope introspection: every permission group is read-only or off."""
    ip_binding_waived: bool = False
    """Local-run waiver (user decision 2026-10-24): keys may lack an IP whitelist. Waives only
    ``ip_not_restricted`` and the KuCoin IP attestation; every other rule stays fatal.
    Env-only (``KEY_POLICY_IP_BINDING_WAIVED``); never to be set on a server (A5d guard)."""


class ScannerSettings(NexusBaseSettings):
    """Market scanning loop settings (``SCANNER_*``)."""

    model_config = SettingsConfigDict(env_prefix="SCANNER_")

    quote_assets: StrTuple = ("USDT",)
    symbols_whitelist: StrTuple = ()
    symbols_blacklist: StrTuple = ()
    min_quote_volume_usd: Decimal = Field(default=Decimal(50_000), ge=0)
    ticker_interval_s: float = Field(default=10.0, ge=1.0)
    metadata_refresh_s: float = Field(default=1_800.0, ge=60.0)
    orderbook_depth: int = Field(default=50, ge=5, le=500)
    max_candidates_per_sweep: int = Field(default=30, ge=1, le=500)
    max_concurrent_requests_per_exchange: int = Field(default=4, ge=1, le=50)
    snapshot_top_k: int = Field(default=20, ge=0, le=1_000)
    heartbeat_ttl_s: int = Field(default=120, ge=10)
    exchange_down_after_failures: int = Field(default=3, ge=1, le=100)
    rate_limit_backoff_s: int = Field(default=60, ge=5, le=3_600)
    ws_enabled: bool = True
    """Stream order books of recently profitable routes over WebSocket (hot-set)."""
    ws_max_streams: int = Field(default=20, ge=0, le=200)
    ws_hot_ttl_s: int = Field(default=300, ge=30, le=3_600)
    latency_check_ms: int = Field(default=2_000, ge=0, le=60_000)
    """A new episode is re-checked on REST books taken this long after detection ("survived
    latency", a measure of how long a spread lives)."""

    @field_validator("quote_assets", "symbols_whitelist", "symbols_blacklist")
    @classmethod
    def _upper(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.strip().upper() for item in value)

    @field_validator("quote_assets")
    @classmethod
    def _quote_assets_usd_pegged(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # Net profit is reported in USD assuming a 1:1 quote peg; restrict to USD stablecoins.
        allowed = {"USDT", "USDC"}
        unsupported = set(value) - allowed
        if not value or unsupported:
            msg = f"quote_assets must be a non-empty subset of {sorted(allowed)}"
            raise ValueError(msg)
        return value


class SpreadSettings(NexusBaseSettings):
    """Net spread estimation & alert thresholds (``SPREAD_*``)."""

    model_config = SettingsConfigDict(env_prefix="SPREAD_")

    min_net_profit_pct: Decimal = Field(default=Decimal("0.3"), gt=0)
    min_net_profit_usd: Decimal = Field(default=Decimal(5), gt=0)
    reference_notional_usd: Decimal = Field(default=Decimal(1_000), gt=0)
    max_orderbook_age_ms: int = Field(default=5_000, ge=100, le=30_000)
    max_book_skew_ms: int = Field(default=3_000, ge=0, le=30_000)
    max_gross_spread_pct: Decimal = Field(default=Decimal(20), gt=0, le=100)
    max_unverified_gross_spread_pct: Decimal = Field(default=Decimal(5), gt=0, le=100)
    default_taker_fee_pct: Decimal = Field(default=Decimal("0.2"), ge=Decimal("0.01"), lt=5)
    include_transfer_cost: bool = True
    transfer_tax_pct: dict[str, Decimal] = Field(
        default_factory=lambda: {"LUNC": Decimal("1.5"), "USTC": Decimal("1.5")}
    )
    """On-chain transfer taxes (percent of the amount moved) the exchanges' withdrawal fee
    does not include, e.g. the Terra Classic burn tax (1.5 % since 2026-08). Keyed by asset,
    not network: conservative if a venue already folds the tax into its fee or moves a
    wrapped token (alerts may be missed, never overstated)."""
    require_verified_transfer: bool = True
    """Alert only routes with a ``VERIFIED`` transfer path (unverified ones are still stored)."""
    alert_cooldown_s: int = Field(default=600, ge=30)

    @field_validator("transfer_tax_pct")
    @classmethod
    def _valid_taxes(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        normalized = {asset.strip().upper(): pct for asset, pct in value.items()}
        if len(normalized) != len(value):
            msg = "SPREAD_TRANSFER_TAX_PCT has duplicate assets (names are case-insensitive)"
            raise ValueError(msg)
        for asset, pct in normalized.items():
            if not Decimal(0) <= pct < Decimal(50):
                msg = f"SPREAD_TRANSFER_TAX_PCT[{asset}] must be a percent in [0, 50)"
                raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.max_book_skew_ms > self.max_orderbook_age_ms:
            msg = "SPREAD_MAX_BOOK_SKEW_MS must not exceed SPREAD_MAX_ORDERBOOK_AGE_MS"
            raise ValueError(msg)
        if self.max_gross_spread_pct <= self.min_net_profit_pct:
            msg = "SPREAD_MAX_GROSS_SPREAD_PCT must exceed SPREAD_MIN_NET_PROFIT_PCT"
            raise ValueError(msg)
        if not (
            self.min_net_profit_pct
            < self.max_unverified_gross_spread_pct
            <= self.max_gross_spread_pct
        ):
            msg = (
                "SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT must be above SPREAD_MIN_NET_PROFIT_PCT "
                "and not above SPREAD_MAX_GROSS_SPREAD_PCT"
            )
            raise ValueError(msg)
        return self


class AlertPolicySettings(NexusBaseSettings):
    """Opportunity alert policy (``ALERT_*``)."""

    model_config = SettingsConfigDict(env_prefix="ALERT_")

    update_min_change_pct: Decimal = Field(default=Decimal(25), gt=0, le=1_000)
    """UPDATE (edit of the episode's message) only when the net profit changed, up or down, by at
    least this relative percentage since the last alert of the episode."""
    update_min_interval_s: int = Field(default=60, ge=0, le=3_600)
    """...and at least this long since the last alert/edit of the episode."""
    max_per_hour: int = Field(default=30, ge=1, le=1_000)
    """Cap of NEW messages per clock hour; the overflow is collapsed into one summary message."""
    send_min_interval_s: float = Field(default=1.0, ge=0, le=60)
    """Telegram: minimum gap between two calls to the chat (<= 1 message/s per chat)."""
    send_max_per_minute: int = Field(default=20, ge=1, le=1_000)
    """Telegram: calls per minute to the chat (a channel allows ~20 messages/min)."""
    sending_stale_s: int = Field(default=600, ge=60, le=86_400)
    """An alert_log row stuck in ``sending`` this long (worker died mid-send) is reaped."""
    language: Literal["en", "ru"] = "en"
    """Language of the opportunity alert texts (``ALERT_LANGUAGE``)."""


class EpisodeSettings(NexusBaseSettings):
    """Opportunity episode tracking (``EPISODE_*``)."""

    model_config = SettingsConfigDict(env_prefix="EPISODE_")

    close_gap_s: int = Field(default=300, ge=10, le=3_600)
    """An episode closes after this long without a qualifying evaluation of its route."""


class QuarantineSettings(NexusBaseSettings):
    """Automatic quarantine of dead routes (``QUARANTINE_*``)."""

    model_config = SettingsConfigDict(env_prefix="QUARANTINE_")

    persist_min: int = Field(default=15, ge=1, le=24 * 60)
    """An episode open this long without a verified transfer path quarantines its route."""
    ttl_h: int = Field(default=24, ge=1, le=24 * 30)
    """Quarantine duration (lifted early when the transfer path becomes verified)."""
    window_h: int = Field(default=6, ge=1, le=7 * 24)
    """Look-back window for recurring unverified episodes of a route."""
    max_episodes: int = Field(default=5, ge=2, le=1_000)
    """This many unverified episodes of a route within the window quarantine it."""

    @model_validator(mode="after")
    def _window_covers_persistence(self) -> Self:
        if self.persist_min > self.window_h * 60:
            msg = "QUARANTINE_PERSIST_MIN must not exceed QUARANTINE_WINDOW_H x 60"
            raise ValueError(msg)
        return self


class DigestSettings(NexusBaseSettings):
    """Daily Telegram digest (``DIGEST_*``)."""

    model_config = SettingsConfigDict(env_prefix="DIGEST_")

    enabled: bool = True
    time: str = "09:00"
    """Local send time ``HH:MM`` in :attr:`tz`."""
    tz: str = "Europe/Moscow"

    @field_validator("time")
    @classmethod
    def _valid_time(cls, value: str) -> str:
        match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
        if match is None:
            msg = "DIGEST_TIME must be HH:MM (24h), e.g. 09:00"
            raise ValueError(msg)
        return match.group(0)

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value.strip())
        except (ZoneInfoNotFoundError, ValueError):
            msg = f"DIGEST_TZ is not a known IANA time zone: {value!r}"
            raise ValueError(msg) from None
        return value.strip()

    @property
    def hour(self) -> int:
        """Send hour."""
        return int(self.time[:2])

    @property
    def minute(self) -> int:
        """Send minute."""
        return int(self.time[3:])


class MaintenanceSettings(NexusBaseSettings):
    """Housekeeping schedule & retention (``MAINTENANCE_*``)."""

    model_config = SettingsConfigDict(env_prefix="MAINTENANCE_")

    snapshot_retention_days: int = Field(default=7, ge=1)
    """Spread snapshots, exchange health, metadata stats."""
    evaluation_retention_days: int = Field(default=30, ge=1)
    episode_retention_days: int = Field(default=90, ge=1)
    """Closed opportunity episodes and the quarantine history (digest analytics)."""
    cleanup_interval_s: int = Field(default=3_600, ge=60)


class WatchdogSettings(NexusBaseSettings):
    """Liveness watchdog and coverage accounting (``WATCHDOG_*``)."""

    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    enabled: bool = True
    interval_s: int = Field(default=300, ge=60)
    """Period of the beat task that checks the scanner and the backup status."""
    scanner_stale_min: int = Field(default=10, ge=2)
    """Alert when the scanner recorded no exchange call for this many minutes."""
    backup_status_path: str = "/backups/last_backup.json"
    """Status file written by ``scripts/backup.sh`` (mounted read-only into the worker)."""
    backup_max_age_h: int = Field(default=26, ge=1)
    """Alert when the last backup finished longer ago than this (daily cron + slack)."""

    @field_validator("backup_status_path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value.strip().startswith("/"):
            msg = "WATCHDOG_BACKUP_STATUS_PATH must be an absolute path"
            raise ValueError(msg)
        return value.strip()
