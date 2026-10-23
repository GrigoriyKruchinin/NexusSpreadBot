"""Modular, per-container settings."""

from nexus.config.groups import (
    CORE_EXCHANGES,
    CelerySettings,
    DatabaseSettings,
    ExchangeCredentials,
    ExchangesSettings,
    LoggingSettings,
    MaintenanceSettings,
    RedisSettings,
    ScannerSettings,
    SpreadSettings,
    TelegramSettings,
)
from nexus.config.roles import (
    AlertsWorkerSettings,
    MaintenanceWorkerSettings,
    MigratorSettings,
    ScannerRoleSettings,
    SchedulerSettings,
)

__all__ = [
    "CORE_EXCHANGES",
    "AlertsWorkerSettings",
    "CelerySettings",
    "DatabaseSettings",
    "ExchangeCredentials",
    "ExchangesSettings",
    "LoggingSettings",
    "MaintenanceSettings",
    "MaintenanceWorkerSettings",
    "MigratorSettings",
    "RedisSettings",
    "ScannerRoleSettings",
    "ScannerSettings",
    "SchedulerSettings",
    "SpreadSettings",
    "TelegramSettings",
]
