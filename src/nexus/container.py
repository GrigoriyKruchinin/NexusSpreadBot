"""Composition root: the only place where concrete implementations are wired together."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import nexus.adapters.cex  # noqa: F401 - registers built-in exchange adapters
from nexus.adapters.key_policy import verify_key_policies
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.roles import (
    AlertsWorkerSettings,
    MaintenanceWorkerSettings,
    ScannerRoleSettings,
)
from nexus.domain.clock import Clock, SystemClock
from nexus.engine.candidates import CandidateFilter, CandidateFinder
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from nexus.infra.redis_store import RedisCooldownStore, RedisHeartbeat, RedisQuarantineStore
from nexus.interfaces.market_data import BaseExchangeAdapter
from nexus.notifications.formatting import OpportunityFormatter
from nexus.notifications.telegram import TelegramNotifier
from nexus.persistence.db import create_engine, create_session_factory
from nexus.persistence.repositories import (
    AlertLogRepository,
    DigestRepository,
    EpisodeRepository,
    EvaluationRepository,
    ExchangeHealthRepository,
    MarketRepository,
    MetadataStatsRepository,
    PaperRepository,
    QuarantineRepository,
    RetentionRepository,
    SnapshotRepository,
)
from nexus.scanner.episodes import EpisodeTracker
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.paper import PaperBook, PaperTrader
from nexus.scanner.quarantine import QuarantineManager
from nexus.scanner.service import Repositories, Scanner, ScannerConfig
from nexus.scanner.streams import OrderBookStreams
from nexus.scanner.universe import UniverseFilter
from nexus.services.alerts import AlertService
from nexus.services.digest import DigestService
from nexus.services.maintenance import RetentionService
from nexus.simulation.portfolio import PaperConfig, allocate_capital
from nexus.workers.dispatch import CeleryAlertDispatcher

log = structlog.get_logger(__name__)


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


def build_paper_book(
    settings: ScannerRoleSettings, sessions: async_sessionmaker[AsyncSession], clock: Clock
) -> PaperBook | None:
    """Shadow paper portfolios (``PAPER_ENABLED``, ``PAPER_VENUE_SETS``): one independent
    :class:`PaperTrader` per venue set with the SAME fixed capital (``PAPER_CAPITAL_USD``),
    trades priced at the paper notional without per-trade transfer cost (inventory is
    rebalanced virtually instead)."""
    paper = settings.paper
    if not paper.enabled:
        return None
    pricing = replace(
        EstimatorConfig.from_settings(settings.spread),
        reference_notional_usd=paper.trade_notional_usd,
        include_transfer_cost=False,
    )
    repository = PaperRepository(sessions)
    traders: dict[str, PaperTrader] = {}
    for name, venues in settings.venue_sets.items():
        usdt, coin_budget = allocate_capital(paper.capital_usd, len(venues), paper.usdt_share_pct)
        traders[name] = PaperTrader(
            PaperConfig(
                usdt_per_exchange=usdt,
                coin_per_route_usd=min(paper.coin_per_route_usd, coin_budget),
                rebalance_threshold_pct=paper.rebalance_threshold_pct,
                rebalance_delay_ms=paper.rebalance_delay_min * 60_000,
                trade_notional_usd=paper.trade_notional_usd,
                transfer_tax_pct=dict(settings.spread.transfer_tax_pct),
                coin_budget_per_venue_usd=coin_budget,
            ),
            repository,
            NetSpreadEstimator(pricing, clock),
            clock,
            portfolio_id=name,
            venues=frozenset(venues),
        )
        log.info(
            "paper_portfolio_configured",
            portfolio=name,
            venues=list(venues),
            capital_usd=str(paper.capital_usd),
        )
    return PaperBook(traders)


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
        # Fail closed before any market data / DB work: a trade-capable key never runs.
        await verify_key_policies(adapters, settings.credentials, settings.key_policy)

        engine = create_engine(settings.database)
        stack.push_async_callback(engine.dispose)
        sessions = create_session_factory(engine)

        redis = redis_client(settings.redis.url.get_secret_value(), settings.redis.socket_timeout_s)
        stack.push_async_callback(redis.aclose)

        spread, scan = settings.spread, settings.scanner
        streams = (
            OrderBookStreams(
                adapters,
                depth=scan.orderbook_depth,
                max_streams=scan.ws_max_streams,
                hot_ttl_ms=scan.ws_hot_ttl_s * 1000,
                # Leave headroom below the estimator's freshness limit; else fall back to REST.
                max_book_age_ms=spread.max_orderbook_age_ms // 2,
                clock=clock,
            )
            if scan.ws_enabled and scan.ws_max_streams > 0
            else None
        )
        if streams is not None:
            stack.push_async_callback(streams.close)
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
                metadata_stats=MetadataStatsRepository(sessions),
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
                latency_check_ms=settings.paper.latency_ms,
                realert_growth_pct=settings.alerts.realert_growth_pct,
            ),
            clock=clock,
            streams=streams,
            episodes=EpisodeTracker(
                EpisodeRepository(sessions),
                close_gap_ms=settings.episodes.close_gap_s * 1000,
                clock=clock,
            ),
            paper=build_paper_book(settings, sessions, clock),
            quarantine=QuarantineManager(
                RedisQuarantineStore(redis, clock),
                QuarantineRepository(sessions),
                persist_ms=settings.quarantine.persist_min * 60_000,
                ttl_ms=settings.quarantine.ttl_h * 3_600_000,
                clock=clock,
                window_ms=settings.quarantine.window_h * 3_600_000,
                max_episodes=settings.quarantine.max_episodes,
            ),
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
            opportunity_formatter=OpportunityFormatter(settings.conditional.venues),
        )
    finally:
        await notifier.close()
        await engine.dispose()


@asynccontextmanager
async def digest_scope(settings: AlertsWorkerSettings) -> AsyncIterator[DigestService]:
    """Digest service for one Celery task (read-only aggregates + Telegram)."""
    engine = create_engine(settings.database, pooled=False)
    notifier = TelegramNotifier(settings.telegram)
    try:
        yield DigestService(
            DigestRepository(
                create_session_factory(engine), conditional_venues=settings.conditional.venues
            ),
            notifier,
            SystemClock(),
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
