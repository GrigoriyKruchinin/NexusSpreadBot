"""Per-container settings loaders.

Each Docker service loads exactly the groups its domain needs. Combined with the per-service
``environment`` mapping in docker compose this guarantees that, for example, the Telegram
worker never receives exchange API keys and the scanner never receives the bot token.
"""

from __future__ import annotations

from typing import Self

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexus.config.groups import (
    AlertPolicySettings,
    CelerySettings,
    ConditionalVenuesSettings,
    DatabaseSettings,
    DigestSettings,
    EpisodeSettings,
    ExchangeCredentials,
    ExchangesSettings,
    KeyPolicySettings,
    LoggingSettings,
    MaintenanceSettings,
    PaperSettings,
    QuarantineSettings,
    RedisSettings,
    ScannerSettings,
    SpreadSettings,
    TelegramSettings,
    WatchdogSettings,
)
from nexus.config.venue_sets import resolve_venue_sets

log = structlog.get_logger(__name__)


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
    digest: DigestSettings
    watchdog: WatchdogSettings
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            celery=CelerySettings(),
            maintenance=MaintenanceSettings(),
            digest=DigestSettings(),
            watchdog=WatchdogSettings(),
            logging=LoggingSettings(),
        )


class ScannerRoleSettings(_RoleSettings):
    """Scanner service: market data, spread engine, persistence, alert dispatch."""

    database: DatabaseSettings
    redis: RedisSettings
    celery: CelerySettings
    exchanges: ExchangesSettings
    conditional: ConditionalVenuesSettings = Field(default_factory=ConditionalVenuesSettings)
    credentials: dict[str, ExchangeCredentials]
    key_policy: KeyPolicySettings = Field(default_factory=KeyPolicySettings)
    scanner: ScannerSettings
    spread: SpreadSettings
    episodes: EpisodeSettings
    paper: PaperSettings
    alerts: AlertPolicySettings
    quarantine: QuarantineSettings
    logging: LoggingSettings

    @model_validator(mode="after")
    def _episode_gap_spans_sweeps(self) -> Self:
        # A route is re-evaluated at most once per sweep: a gap shorter than two sweeps would
        # close and reopen episodes of a persisting spread.
        if self.episodes.close_gap_s < 2 * self.scanner.ticker_interval_s:
            msg = "EPISODE_CLOSE_GAP_S must be at least 2 x SCANNER_TICKER_INTERVAL_S"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _conditional_subset_of_enabled(self) -> Self:
        """Fail fast on an explicit list that names a venue that is not enabled (typo guard)."""
        unknown = sorted(set(self.conditional.venues) - set(self.exchanges.enabled))
        if unknown:
            msg = f"CONDITIONAL_VENUES not in EXCHANGES_ENABLED: {', '.join(unknown)}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _venue_sets_valid(self) -> Self:
        """Fail closed on a bad ``PAPER_VENUE_SETS`` (the error names the set and venue)."""
        _ = self.venue_sets  # resolved eagerly so a bad spec stops startup
        return self

    @property
    def venue_sets(self) -> dict[str, tuple[str, ...]]:
        """Resolved shadow-portfolio venue sets, ``all`` first."""
        return resolve_venue_sets(
            self.paper.venue_sets,
            self.exchanges.enabled,
            self.conditional.venues,
            strict="venue_sets" in self.paper.model_fields_set,
        )

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        exchanges = ExchangesSettings()
        conditional = ConditionalVenuesSettings()
        if "venues" not in conditional.model_fields_set:
            # Default list: follow a narrowed EXCHANGES_ENABLED instead of crashing on a
            # variable the operator never set. An explicit list is validated strictly.
            kept = tuple(v for v in conditional.venues if v in exchanges.enabled)
            if kept != conditional.venues:
                log.warning(
                    "conditional_venues_defaulted",
                    default=list(conditional.venues),
                    effective=list(kept),
                    exchanges=list(exchanges.enabled),
                )
                conditional = ConditionalVenuesSettings(venues=kept)
        return cls(
            database=DatabaseSettings(),
            redis=RedisSettings(),
            celery=CelerySettings(),
            exchanges=exchanges,
            conditional=conditional,
            credentials={n: ExchangeCredentials.for_exchange(n) for n in exchanges.enabled},
            key_policy=KeyPolicySettings(),
            scanner=ScannerSettings(),
            spread=SpreadSettings(),
            episodes=EpisodeSettings(),
            paper=PaperSettings(),
            alerts=AlertPolicySettings(),
            quarantine=QuarantineSettings(),
            logging=LoggingSettings(),
        )


class AlertsWorkerSettings(_RoleSettings):
    """Celery ``alerts`` worker: reads opportunities, sends Telegram messages."""

    database: DatabaseSettings
    celery: CelerySettings
    telegram: TelegramSettings
    conditional: ConditionalVenuesSettings = Field(default_factory=ConditionalVenuesSettings)
    watchdog: WatchdogSettings = Field(default_factory=WatchdogSettings)
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            database=DatabaseSettings(),
            celery=CelerySettings(),
            telegram=TelegramSettings(),
            conditional=ConditionalVenuesSettings(),
            watchdog=WatchdogSettings(),
            logging=LoggingSettings(),
        )


class MaintenanceWorkerSettings(_RoleSettings):
    """Celery ``maintenance`` worker: retention cleanup, health aggregation."""

    database: DatabaseSettings
    celery: CelerySettings
    maintenance: MaintenanceSettings
    watchdog: WatchdogSettings = Field(default_factory=WatchdogSettings)
    logging: LoggingSettings

    @classmethod
    def load(cls) -> Self:
        """Load from the process environment."""
        return cls(
            database=DatabaseSettings(),
            celery=CelerySettings(),
            maintenance=MaintenanceSettings(),
            watchdog=WatchdogSettings(),
            logging=LoggingSettings(),
        )
