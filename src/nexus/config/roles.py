"""Per-container settings loaders.

Each Docker service loads exactly the groups its domain needs. Combined with the per-service
``environment`` mapping in docker compose this guarantees that, for example, the Telegram
worker never receives exchange API keys and the scanner never receives the bot token.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from nexus.config.groups import (
    CelerySettings,
    DatabaseSettings,
    EpisodeSettings,
    ExchangeCredentials,
    ExchangesSettings,
    LoggingSettings,
    MaintenanceSettings,
    PaperSettings,
    RedisSettings,
    ScannerSettings,
    SpreadSettings,
    TelegramSettings,
)


class _RoleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class MigratorSettings(_RoleSettings):
    """Alembic migrator: database only."""

    database: DatabaseSettings
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(database=DatabaseSettings(), logging=LoggingSettings())


class SchedulerSettings(_RoleSettings):
    """Celery beat: broker + schedule only, no database or exchange secrets."""

    celery: CelerySettings
    maintenance: MaintenanceSettings
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            celery=CelerySettings(),
            maintenance=MaintenanceSettings(),
            logging=LoggingSettings(),
        )


class ScannerRoleSettings(_RoleSettings):
    """Scanner service: market data, spread engine, persistence, alert dispatch."""

    database: DatabaseSettings
    redis: RedisSettings
    celery: CelerySettings
    exchanges: ExchangesSettings
    credentials: dict[str, ExchangeCredentials]
    scanner: ScannerSettings
    spread: SpreadSettings
    episodes: EpisodeSettings
    paper: PaperSettings
    logging: LoggingSettings

    @model_validator(mode="after")
    def _episode_gap_spans_sweeps(self) -> Self:
        # A route is re-evaluated at most once per sweep: a gap shorter than two sweeps would
        # close and reopen episodes of a persisting spread.
        if self.episodes.close_gap_s < 2 * self.scanner.ticker_interval_s:
            msg = "EPISODE_CLOSE_GAP_S must be at least 2 x SCANNER_TICKER_INTERVAL_S"
            raise ValueError(msg)
        return self

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        exchanges = ExchangesSettings()
        return cls(
            database=DatabaseSettings(),
            redis=RedisSettings(),
            celery=CelerySettings(),
            exchanges=exchanges,
            credentials={n: ExchangeCredentials.for_exchange(n) for n in exchanges.enabled},
            scanner=ScannerSettings(),
            spread=SpreadSettings(),
            episodes=EpisodeSettings(),
            paper=PaperSettings(),
            logging=LoggingSettings(),
        )


class AlertsWorkerSettings(_RoleSettings):
    """Celery ``alerts`` worker: reads opportunities, sends Telegram messages."""

    database: DatabaseSettings
    celery: CelerySettings
    telegram: TelegramSettings
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            database=DatabaseSettings(),
            celery=CelerySettings(),
            telegram=TelegramSettings(),
            logging=LoggingSettings(),
        )


class MaintenanceWorkerSettings(_RoleSettings):
    """Celery ``maintenance`` worker: retention cleanup, health aggregation."""

    database: DatabaseSettings
    celery: CelerySettings
    maintenance: MaintenanceSettings
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            database=DatabaseSettings(),
            celery=CelerySettings(),
            maintenance=MaintenanceSettings(),
            logging=LoggingSettings(),
        )
