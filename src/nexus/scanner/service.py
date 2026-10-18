"""Scanner orchestrator: tickers -> candidates -> order books -> net spread -> persist/alert.

The orchestrator depends only on interfaces; it never branches on exchange names, so new
exchanges plug in through the adapter registry without changes here.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from nexus.domain.clock import Clock
from nexus.domain.errors import (
    DataValidationError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from nexus.domain.events import (
    ExchangeStatus,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
    decimal_str,
)
from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, Ticker
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import CandidateFinder, RouteQuote
from nexus.engine.estimator import NetSpreadEstimator
from nexus.engine.transfer import select_transfer_route
from nexus.interfaces.coordination import IAlertDispatcher, ICooldownStore, IHeartbeat
from nexus.interfaces.market_data import BaseExchangeAdapter, ITradingFeeSource
from nexus.interfaces.repositories import (
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    ISnapshotRepository,
)
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.universe import MarketUniverse, UniverseFilter

log = structlog.get_logger(__name__)

HEARTBEAT_SERVICE = "scanner"
MIN_LIVE_EXCHANGES = 2
EVENT_EMIT_TIMEOUT_S = 5.0
FEE_LOOKUPS_PER_EXCHANGE_PER_SWEEP = 3
"""Per-symbol account fee lookups are lazy (alert candidates only) and rate-limit friendly."""
FEE_LOOKUP_TIMEOUT_S = 2.0
"""A slow fee endpoint must not hold up evaluation: the leg keeps its (estimated) default fee."""
FEE_LOOKUP_MAX_ATTEMPTS = 3
FEE_CACHE_TTL_MS = 6 * 3600 * 1000
"""Account fee tiers change (30-day volume, promos): looked-up fees are re-fetched after this."""

BookKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    """Loop parameters (see ``ScannerSettings`` / ``SpreadSettings``)."""

    ticker_interval_s: float
    metadata_refresh_s: float
    orderbook_depth: int
    max_candidates_per_sweep: int
    max_concurrent_requests_per_exchange: int
    snapshot_top_k: int
    heartbeat_ttl_s: int
    alert_cooldown_s: int
    book_deadline_s: float
    """Overall budget for fetching + evaluating candidate books in one sweep; routes whose
    books are not ready in time are skipped (they would be stale anyway)."""


@dataclass(frozen=True, slots=True)
class Repositories:
    """Persistence ports used by the scanner."""

    markets: IMarketRepository
    snapshots: ISnapshotRepository
    evaluations: IEvaluationRepository
    health: IExchangeHealthRepository


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Summary of one sweep (for logs and tests)."""

    exchanges_ok: int
    routes: int
    candidates: int
    evaluations: int
    alerts: int
    timed_out: int = 0


class Scanner:
    """Long-running scanning service."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, BaseExchangeAdapter],
        authenticated: Mapping[str, bool],
        estimator: NetSpreadEstimator,
        finder: CandidateFinder,
        universe_filter: UniverseFilter,
        repositories: Repositories,
        cooldowns: ICooldownStore,
        heartbeat: IHeartbeat,
        dispatcher: IAlertDispatcher,
        health: ExchangeHealthTracker,
        config: ScannerConfig,
        clock: Clock,
    ) -> None:
        self._adapters = dict(adapters)
        self._authenticated = dict(authenticated)
        self._estimator = estimator
        self._finder = finder
        self._filter = universe_filter
        self._repos = repositories
        self._cooldowns = cooldowns
        self._heartbeat = heartbeat
        self._dispatcher = dispatcher
        self._health = health
        self._config = config
        self._clock = clock
        self._universe = MarketUniverse(markets={})
        self._account_fees: dict[BookKey, tuple[Decimal, int]] = {}
        """Per-symbol account taker fees ``(fee, fetched_at_ms)``; survive metadata refreshes
        until :data:`FEE_CACHE_TTL_MS`."""
        self._fee_checked: dict[BookKey, int] = {}
        """Lookups that completed (with or without a fee) -> completion time (ms)."""
        self._fee_attempts: dict[BookKey, int] = {}
        self._fee_semaphores = {name: asyncio.Semaphore(1) for name in self._adapters}
        self._semaphores = {
            name: asyncio.Semaphore(config.max_concurrent_requests_per_exchange)
            for name in self._adapters
        }

    @property
    def universe(self) -> MarketUniverse:
        """Current scannable universe."""
        return self._universe

    # ------------------------------------------------------------------ lifecycle

    async def run(self, stop: asyncio.Event) -> None:
        """Run until ``stop`` is set; in-flight work is cancelled promptly on stop."""
        try:
            if not await self._until_stopped(self.refresh_metadata(), stop):
                return
            await self._announce_start()
            last_refresh = time.monotonic()
            while not stop.is_set():
                started = time.monotonic()
                if started - last_refresh >= self._config.metadata_refresh_s:
                    await self._until_stopped(self.refresh_metadata(), stop)
                    last_refresh = time.monotonic()
                if stop.is_set() or not await self._until_stopped(self.sweep(), stop):
                    break
                elapsed = time.monotonic() - started
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop.wait(), timeout=max(0.0, self._config.ticker_interval_s - elapsed)
                    )
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self._emit(ScannerStopped(reason="shutdown")), EVENT_EMIT_TIMEOUT_S
                )

    async def _until_stopped(self, work: Coroutine[Any, Any, object], stop: asyncio.Event) -> bool:
        """Run ``work`` unless ``stop`` fires first; errors are logged, never fatal.

        Returns False when the scanner is stopping.
        """
        task = asyncio.create_task(work)
        stopper = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            return False
        if task.cancelled():
            return False
        if (error := task.exception()) is not None:
            log.error("scanner_iteration_failed", error=repr(error)[:300])
        return not stop.is_set()

    async def _announce_start(self) -> None:
        event = ScannerStarted(
            exchanges=tuple(
                ExchangeStatus(
                    name=name,
                    authenticated=self._authenticated.get(name, False),
                    markets=len(self._universe.symbols_for(name)),
                )
                for name in sorted(self._adapters)
            ),
            min_net_profit_pct=decimal_str(self._estimator.config.min_net_profit_pct),
            min_net_profit_usd=decimal_str(self._estimator.config.min_net_profit_usd),
            reference_notional_usd=decimal_str(self._estimator.config.reference_notional_usd),
            common_symbols=len(self._universe.common_symbols),
        )
        await self._emit(event)

    # ------------------------------------------------------------------ metadata

    async def refresh_metadata(self) -> MarketUniverse:
        """Reload markets and transfer metadata from every exchange."""
        markets: dict[str, Sequence[MarketInfo]] = {}
        transfers: dict[str, Mapping[str, AssetTransferInfo] | None] = {}

        async def load(name: str, adapter: BaseExchangeAdapter) -> None:
            started = time.monotonic()
            try:
                markets[name] = await adapter.load_markets()
                transfers[name] = await adapter.load_transfer_info()
            except ExchangeError as exc:
                await self._record(name, "load_metadata", started, exc)
                previous = self._universe.markets.get(name)
                if previous:
                    markets[name] = list(previous.values())
                    # Stale transfer status could hide a new suspension: downgrade to unknown.
                    transfers[name] = None
                return
            await self._record(name, "load_metadata", started, None)

        await asyncio.gather(*(load(n, a) for n, a in self._adapters.items()))
        self._universe = MarketUniverse.build(markets, transfers, self._filter).with_taker_fees(
            self._fresh_account_fees()
        )
        all_markets = [
            m for by_symbol in self._universe.markets.values() for m in by_symbol.values()
        ]
        await self._repos.markets.upsert_markets(all_markets)
        log.info(
            "metadata_refreshed",
            exchanges={n: len(self._universe.symbols_for(n)) for n in self._adapters},
            common_symbols=len(self._universe.common_symbols),
        )
        return self._universe

    # ------------------------------------------------------------------ sweep

    async def sweep(self) -> SweepResult:
        """One scanning iteration."""
        tickers = await self._fetch_all_tickers()
        routes = self._finder.rank_routes(tickers, self._universe.markets)
        if self._config.snapshot_top_k and routes:
            await self._repos.snapshots.add_snapshots(
                datetime.now(tz=UTC), routes[: self._config.snapshot_top_k]
            )
        candidates = self._finder.select(routes, self._config.max_candidates_per_sweep)
        evaluations, timed_out = await self._evaluate_candidates(candidates)
        ids = await self._repos.evaluations.add_evaluations(evaluations)
        alerts = 0
        for evaluation_id, evaluation in zip(ids, evaluations, strict=True):
            if evaluation.is_alertable and await self._alert(evaluation_id, evaluation):
                alerts += 1
        if len(tickers) >= MIN_LIVE_EXCHANGES:
            # A sweep with fewer than two live venues cannot find routes: stay "unhealthy".
            await self._heartbeat.beat(HEARTBEAT_SERVICE, self._config.heartbeat_ttl_s)
        result = SweepResult(
            exchanges_ok=len(tickers),
            routes=len(routes),
            candidates=len(candidates),
            evaluations=len(evaluations),
            alerts=alerts,
            timed_out=timed_out,
        )
        log.info(
            "sweep_done",
            exchanges_ok=result.exchanges_ok,
            routes=result.routes,
            candidates=result.candidates,
            evaluations=result.evaluations,
            alerts=result.alerts,
            timed_out=result.timed_out,
        )
        return result

    async def _alert(self, evaluation_id: int, evaluation: SpreadEvaluation) -> bool:
        key = f"alert:{evaluation.route_key}"
        if not await self._cooldowns.acquire(key, self._config.alert_cooldown_s):
            return False
        try:
            await self._dispatcher.dispatch_opportunity(evaluation_id)
        except Exception:
            log.exception("alert_dispatch_failed", evaluation_id=evaluation_id)
            with contextlib.suppress(Exception):
                await self._cooldowns.release(key)
            return False
        log.info(
            "opportunity_alerted",
            route=evaluation.route_key,
            net_profit_pct=str(evaluation.breakdown.net_profit_pct)
            if evaluation.breakdown
            else None,
            evaluation_id=evaluation_id,
        )
        return True

    async def _fetch_all_tickers(self) -> dict[str, Mapping[str, Ticker]]:
        now = self._clock.now_ms()
        active = {
            name: adapter
            for name, adapter in self._adapters.items()
            if self._universe.symbols_for(name) and not self._health.is_paused(name, now)
        }

        async def tickers_of(
            name: str, adapter: BaseExchangeAdapter
        ) -> Mapping[str, Ticker] | None:
            started = time.monotonic()
            try:
                tickers = await adapter.fetch_tickers(sorted(self._universe.symbols_for(name)))
            except ExchangeError as exc:
                await self._record(name, "fetch_tickers", started, exc)
                return None
            await self._record(name, "fetch_tickers", started, None)
            return tickers

        results = await asyncio.gather(*(tickers_of(n, a) for n, a in active.items()))
        return {name: t for name, t in zip(active, results, strict=True) if t is not None}

    async def _record(
        self, exchange: str, operation: str, started: float, error: ExchangeError | None
    ) -> None:
        latency = int((time.monotonic() - started) * 1000)
        now = self._clock.now_ms()
        if error is None:
            event = self._health.record_success(exchange, now)
        else:
            log.warning(
                "exchange_call_failed", exchange=exchange, operation=operation, error=str(error)
            )
            event = self._health.record_failure(
                exchange, now, str(error), rate_limited=isinstance(error, ExchangeRateLimitError)
            )
        try:
            await self._repos.health.record(
                exchange,
                operation,
                ok=error is None,
                latency_ms=latency,
                error=str(error) if error else None,
            )
        except Exception:
            log.exception("health_record_failed", exchange=exchange)
        if event is not None:
            await self._emit(event)

    async def _evaluate_candidates(
        self, candidates: Sequence[RouteQuote]
    ) -> tuple[list[SpreadEvaluation], int]:
        """Fetch books (shared per exchange/symbol) and evaluate each route as soon as both
        of its books are available, within an overall deadline."""
        books: dict[BookKey, asyncio.Task[OrderBook | None]] = {}

        def book_task(exchange: str, symbol: str) -> asyncio.Task[OrderBook | None]:
            key = (exchange, symbol)
            if key not in books:
                books[key] = asyncio.create_task(self._fetch_book(exchange, symbol))
            return books[key]

        fee_tasks = {
            key: asyncio.create_task(self._refine_fee(*key))
            for key in self._fee_lookups(candidates)
        }

        async def evaluate(route: RouteQuote) -> SpreadEvaluation | None:
            legs = ((route.buy_exchange, route.symbol), (route.sell_exchange, route.symbol))
            buy_book, sell_book, *_ = await asyncio.gather(
                book_task(*legs[0]),
                book_task(*legs[1]),
                *(fee_tasks[leg] for leg in legs if leg in fee_tasks),
            )
            if buy_book is None or sell_book is None:
                return None
            return self._evaluate(route, buy_book, sell_book)

        tasks = [asyncio.create_task(evaluate(route)) for route in candidates]
        if not tasks:
            return [], 0
        done, pending = await asyncio.wait(tasks, timeout=self._config.book_deadline_s)
        helpers = (*books.values(), *fee_tasks.values())
        for task in (*pending, *helpers):
            task.cancel()
        await asyncio.gather(*pending, *helpers, return_exceptions=True)
        evaluations = [
            result
            for task in tasks
            if task in done and not task.cancelled() and task.exception() is None
            if (result := task.result()) is not None
        ]
        if pending:
            log.warning("book_deadline_exceeded", routes=len(pending))
        return evaluations, len(pending)

    def _fresh_account_fees(self) -> dict[BookKey, Decimal]:
        """Looked-up fees younger than the TTL (expired ones are dropped)."""
        now = self._clock.now_ms()
        self._account_fees = {
            key: entry
            for key, entry in self._account_fees.items()
            if now - entry[1] < FEE_CACHE_TTL_MS
        }
        return {key: fee for key, (fee, _) in self._account_fees.items()}

    def _fee_lookup_due(self, key: BookKey, market: MarketInfo) -> bool:
        checked_at = self._fee_checked.get(key)
        if checked_at is None:
            return market.taker_fee_is_default
        return self._clock.now_ms() - checked_at >= FEE_CACHE_TTL_MS

    def _fee_lookups(self, candidates: Sequence[RouteQuote]) -> list[BookKey]:
        """Candidate legs on a default (or expired) fee whose adapter can look it up."""
        budget: dict[str, int] = {}
        keys: list[BookKey] = []
        for route in candidates:
            for key in ((route.buy_exchange, route.symbol), (route.sell_exchange, route.symbol)):
                exchange = key[0]
                market = self._universe.market(*key)
                if (
                    key in keys
                    or market is None
                    or not self._fee_lookup_due(key, market)
                    or not self._authenticated.get(exchange, False)
                    or not isinstance(self._adapters[exchange], ITradingFeeSource)
                    or budget.get(exchange, 0) >= FEE_LOOKUPS_PER_EXCHANGE_PER_SWEEP
                ):
                    continue
                budget[exchange] = budget.get(exchange, 0) + 1
                keys.append(key)
        return keys

    async def _refine_fee(self, exchange: str, symbol: str) -> None:
        """Replace the default fee of one market by the account fee (never raises).

        Transient failures (timeout, unavailable, rate limit) are retried in later sweeps up to
        :data:`FEE_LOOKUP_MAX_ATTEMPTS`; anything else keeps the default fee until the TTL.
        """
        key = (exchange, symbol)
        adapter = self._adapters[exchange]
        if not isinstance(adapter, ITradingFeeSource):
            return
        try:
            # The timeout covers waiting for the lookup slot too, so a queue of lookups never
            # holds a route past the book deadline.
            async with asyncio.timeout(FEE_LOOKUP_TIMEOUT_S), self._fee_semaphores[exchange]:
                if self._health.is_paused(exchange, self._clock.now_ms()):
                    return
                fee = await adapter.fetch_taker_fee(symbol)
        except (TimeoutError, ExchangeUnavailableError, ExchangeRateLimitError) as exc:
            log.info("trading_fee_failed", exchange=exchange, symbol=symbol, error=str(exc))
            if isinstance(exc, ExchangeRateLimitError):
                self._health.pause(exchange, self._clock.now_ms())
            attempts = self._fee_attempts.get(key, 0) + 1
            self._fee_attempts[key] = attempts
            if attempts >= FEE_LOOKUP_MAX_ATTEMPTS:
                self._mark_fee_checked(key)
            return
        except Exception:
            log.exception("trading_fee_error", exchange=exchange, symbol=symbol)
            self._mark_fee_checked(key)
            return
        self._mark_fee_checked(key)
        if fee is None:
            return
        self._account_fees[key] = (fee, self._clock.now_ms())
        self._universe = self._universe.with_taker_fees({key: fee})
        log.info("trading_fee_refined", exchange=exchange, symbol=symbol, taker_fee=str(fee))

    def _mark_fee_checked(self, key: BookKey) -> None:
        self._fee_checked[key] = self._clock.now_ms()
        self._fee_attempts.pop(key, None)

    async def _fetch_book(self, exchange: str, symbol: str) -> OrderBook | None:
        async with self._semaphores[exchange]:
            if self._health.is_paused(exchange, self._clock.now_ms()):
                return None
            try:
                return await self._adapters[exchange].fetch_order_book(
                    symbol, self._config.orderbook_depth
                )
            except ExchangeError as exc:
                log.info("order_book_failed", exchange=exchange, symbol=symbol, error=str(exc))
                if isinstance(exc, ExchangeRateLimitError):
                    self._health.pause(exchange, self._clock.now_ms())
                return None

    def _evaluate(
        self, route: RouteQuote, buy_book: OrderBook, sell_book: OrderBook
    ) -> SpreadEvaluation | None:
        buy_market = self._universe.market(route.buy_exchange, route.symbol)
        sell_market = self._universe.market(route.sell_exchange, route.symbol)
        if buy_market is None or sell_market is None:
            return None
        transfer = select_transfer_route(
            self._universe.transfer_info(route.buy_exchange, buy_market.base),
            self._universe.transfer_info(route.sell_exchange, sell_market.base),
        )
        try:
            return self._estimator.evaluate(
                buy_book=buy_book,
                sell_book=sell_book,
                buy_market=buy_market,
                sell_market=sell_market,
                transfer=transfer,
            )
        except (ValueError, ArithmeticError, DataValidationError):
            log.exception("evaluation_failed", route=route.symbol)
            return None

    async def _emit(self, event: SystemEvent) -> None:
        try:
            await self._dispatcher.dispatch_event(event)
        except Exception:
            log.exception("event_dispatch_failed", kind=event.kind)
