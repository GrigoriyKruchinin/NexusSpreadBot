"""Composition root: the only place where concrete implementations are wired together."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from redis.asyncio import Redis

import nexus.adapters.cex  # noqa: F401 - registers built-in exchange adapters
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.roles import (
    AlertsWorkerSettings,
    MaintenanceWorkerSettings,
    ScannerRoleSettings,
)
from nexus.domain.clock import SystemClock
from nexus.engine.candidates import CandidateFilter, CandidateFinder
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.infra.redis_store import RedisCooldownStore, RedisHeartbeat
from nexus.interfaces.market_data import BaseExchangeAdapter
from nexus.notifications.telegram import TelegramNotifier
from nexus.persistence.db import create_engine, create_session_factory
from nexus.persistence.repositories import (
    AlertLogRepository,
    EvaluationRepository,
    ExchangeHealthRepository,
    MarketRepository,
    RetentionRepository,
    SnapshotRepository,
)
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.service import Repositories, Scanner, ScannerConfig
from nexus.scanner.universe import UniverseFilter
from nexus.services.alerts import AlertService
from nexus.services.maintenance import RetentionService
from nexus.workers.dispatch import CeleryAlertDispatcher


def build_adapters(settings: ScannerRoleSettings) -> dict[str, BaseExchangeAdapter]:
    """Instantiate the enabled exchange adapters (unknown names fail fast)."""
    options = AdapterOptions.from_settings(
        timeout_ms=settings.exchanges.request_timeout_ms,
        default_taker_fee_pct=settings.spread.default_taker_fee_pct,
    )
    return {
        name: exchange_registry.create(name, settings.credentials[name], options)
        for name in settings.exchanges.enabled
    }


def redis_client(url: str, socket_timeout_s: float) -> Redis:
    """Async Redis client."""
    return Redis.from_url(url, socket_timeout=socket_timeout_s, decode_responses=True)


@asynccontextmanager
async def scanner_scope(settings: ScannerRoleSettings) -> AsyncIterator[Scanner]:
    """Build a fully wired :class:`Scanner` and release every resource on exit."""
    from nexus.workers.app import create_celery_app

    async with AsyncExitStack() as stack:
        clock = SystemClock()
        adapters = build_adapters(settings)
        for adapter in adapters.values():
            stack.push_async_callback(adapter.close)

        engine = create_engine(settings.database)
        stack.push_async_callback(engine.dispose)
        sessions = create_session_factory(engine)

        redis = redis_client(settings.redis.url.get_secret_value(), settings.redis.socket_timeout_s)
        stack.push_async_callback(redis.aclose)

        spread, scan = settings.spread, settings.scanner
        yield Scanner(
            adapters=adapters,
            authenticated={n: c.is_configured for n, c in settings.credentials.items()},
            estimator=NetSpreadEstimator(EstimatorConfig.from_settings(spread), clock),
            finder=CandidateFinder(
                CandidateFilter(
                    min_net_profit_pct=spread.min_net_profit_pct,
                    max_gross_spread_pct=spread.max_gross_spread_pct,
                    min_quote_volume_usd=scan.min_quote_volume_usd,
                )
            ),
            universe_filter=UniverseFilter(
                quote_assets=frozenset(scan.quote_assets),
                whitelist=frozenset(scan.symbols_whitelist),
                blacklist=frozenset(scan.symbols_blacklist),
            ),
            repositories=Repositories(
                markets=MarketRepository(sessions),
                snapshots=SnapshotRepository(sessions),
                evaluations=EvaluationRepository(sessions),
                health=ExchangeHealthRepository(sessions),
            ),
            cooldowns=RedisCooldownStore(redis),
            heartbeat=RedisHeartbeat(redis, clock),
            dispatcher=CeleryAlertDispatcher(create_celery_app(settings.celery)),
            health=ExchangeHealthTracker(
                down_after_failures=scan.exchange_down_after_failures,
                rate_limit_backoff_ms=scan.rate_limit_backoff_s * 1000,
            ),
            config=ScannerConfig(
                ticker_interval_s=scan.ticker_interval_s,
                metadata_refresh_s=scan.metadata_refresh_s,
                orderbook_depth=scan.orderbook_depth,
                max_candidates_per_sweep=scan.max_candidates_per_sweep,
                max_concurrent_requests_per_exchange=scan.max_concurrent_requests_per_exchange,
                snapshot_top_k=scan.snapshot_top_k,
                heartbeat_ttl_s=scan.heartbeat_ttl_s,
                alert_cooldown_s=spread.alert_cooldown_s,
                # Books older than the freshness limit are rejected anyway.
                book_deadline_s=max(2.0, spread.max_orderbook_age_ms / 1000),
            ),
            clock=clock,
        )


@asynccontextmanager
async def alert_service_scope(settings: AlertsWorkerSettings) -> AsyncIterator[AlertService]:
    """Alert service for one Celery task (fresh event loop => unpooled engine)."""
    engine = create_engine(settings.database, pooled=False)
    sessions = create_session_factory(engine)
    notifier = TelegramNotifier(settings.telegram)
    try:
        yield AlertService(
            evaluations=EvaluationRepository(sessions),
            alert_log=AlertLogRepository(sessions),
            notifier=notifier,
            clock=SystemClock(),
            max_age_s=settings.telegram.alert_max_age_s,
            event_max_age_s=settings.telegram.event_max_age_s,
        )
    finally:
        await notifier.close()
        await engine.dispose()


@asynccontextmanager
async def retention_scope(settings: MaintenanceWorkerSettings) -> AsyncIterator[RetentionService]:
    """Retention service for one Celery task."""
    engine = create_engine(settings.database, pooled=False)
    try:
        yield RetentionService(
            RetentionRepository(create_session_factory(engine)), settings.maintenance
        )
    finally:
        await engine.dispose()
