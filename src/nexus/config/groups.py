"""Domain-specific settings groups.

Every group reads only variables with its own prefix. Containers compose the groups they
need via the role loaders in :mod:`nexus.config.roles`; a group that is never instantiated
in a container never requires (or sees) its secrets.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Self

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


class ExchangesSettings(NexusBaseSettings):
    """Which exchanges are enabled and how to talk to them (``EXCHANGES_*``)."""

    model_config = SettingsConfigDict(env_prefix="EXCHANGES_")

    enabled: StrTuple = ("bybit", "binance", "okx", "gateio", "kucoin", "mexc", "bitget")
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
    require_verified_transfer: bool = True
    """Alert only routes with a ``VERIFIED`` transfer path (unverified ones are still stored)."""
    alert_cooldown_s: int = Field(default=600, ge=30)

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

    realert_growth_pct: Decimal = Field(default=Decimal(50), gt=0, le=1_000)
    """Re-alert an open episode only when its net profit grew by at least this percentage
    over the last alerted value (one alert per episode otherwise)."""


class EpisodeSettings(NexusBaseSettings):
    """Opportunity episode tracking (``EPISODE_*``)."""

    model_config = SettingsConfigDict(env_prefix="EPISODE_")

    close_gap_s: int = Field(default=60, ge=10, le=3_600)
    """An episode closes after this long without a qualifying evaluation of its route."""


class PaperSettings(NexusBaseSettings):
    """Paper trading simulation (``PAPER_*``)."""

    model_config = SettingsConfigDict(env_prefix="PAPER_")

    latency_ms: int = Field(default=2_000, ge=0, le=60_000)
    """Simulated detection-to-execution latency: a new episode is re-checked on REST books
    taken this long after detection ("survived latency")."""


class MaintenanceSettings(NexusBaseSettings):
    """Housekeeping schedule & retention (``MAINTENANCE_*``)."""

    model_config = SettingsConfigDict(env_prefix="MAINTENANCE_")

    snapshot_retention_days: int = Field(default=7, ge=1)
    evaluation_retention_days: int = Field(default=30, ge=1)
    cleanup_interval_s: int = Field(default=3_600, ge=60)
