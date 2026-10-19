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
from nexus.domain.episodes import AlertKind, EpisodeCloseReason, OpportunityEpisode
from nexus.domain.errors import (
    DataValidationError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from nexus.domain.events import (
    AlertContext,
    EpisodeClosed,
    ExchangeStatus,
    QuarantinedRoute,
    RoutesQuarantined,
    ScannerStarted,
    ScannerStopped,
    SystemEvent,
    decimal_str,
)
from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, Ticker
from nexus.domain.quarantine import QuarantineReason, RouteQuarantine, route_key
from nexus.domain.spread import (
    EvaluationStatus,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)
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
from nexus.scanner.episodes import EpisodeTracker
from nexus.scanner.health import ExchangeHealthTracker
from nexus.scanner.quarantine import QuarantineManager
from nexus.scanner.streams import OrderBookStreams
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
QUARANTINE_ANNOUNCE_COOLDOWN_S = 7 * 24 * 3600
"""A route that stays dead re-quarantines daily; the message is repeated at most weekly."""
PARKED_RECORD_INTERVAL_MS = 60_000
"""Quarantined routes are recorded (ticker level) at most once per minute per route."""
EPISODE_ALERT_KEY_TTL_S = 24 * 3600
"""Redis dedup key per (episode, alert number): an episode alert is queued at most once."""
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
    latency_check_ms: int = 2_000
    """A newly opened episode is re-checked on REST books this long after detection."""
    realert_growth_pct: Decimal = Decimal(50)
    """Re-alert an episode when its net profit grew by this % since the last alert."""


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
    streamed_books: int = 0
    quarantined: int = 0
    """Routes skipped this sweep because they are quarantined."""


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
        streams: OrderBookStreams | None = None,
        episodes: EpisodeTracker | None = None,
        quarantine: QuarantineManager | None = None,
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
        self._streams = streams
        self._episodes = episodes
        self._quarantine = quarantine
        self._new_quarantines: list[RouteQuarantine] = []
        self._parked_at: dict[str, int] = {}
        """Last stored ticker-level record per quarantined route (rate limit)."""
        self._latency_checks: set[asyncio.Task[None]] = set()
        self._streamed_books = 0
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
            if self._episodes is not None:
                await self._announce_closed(await self._episodes.start())
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
            for check in tuple(self._latency_checks):
                check.cancel()
            await asyncio.gather(*self._latency_checks, return_exceptions=True)
            if self._streams is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._streams.close(), EVENT_EMIT_TIMEOUT_S)
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
                    transfer_coverage_pct=self._universe.transfer_coverage_pct(name),
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
        await self._lift_verified_quarantines()
        all_markets = [
            m for by_symbol in self._universe.markets.values() for m in by_symbol.values()
        ]
        await self._repos.markets.upsert_markets(all_markets)
        log.info(
            "metadata_refreshed",
            exchanges={n: len(self._universe.symbols_for(n)) for n in self._adapters},
            common_symbols=len(self._universe.common_symbols),
            transfer_coverage_pct={
                n: self._universe.transfer_coverage_pct(n) for n in self._adapters
            },
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
        quarantined = await self._refresh_quarantine()
        live = [r for r in routes if _route_key(r) not in quarantined]
        parked = [r for r in routes if _route_key(r) in quarantined]
        candidates = self._finder.select(live, self._config.max_candidates_per_sweep)
        parked_evaluations = self._parked_evaluations(parked, quarantined)
        self._streamed_books = 0
        evaluations, timed_out = await self._evaluate_candidates(candidates)
        await self._quarantine_unavailable(evaluations)
        await self._update_streams(evaluations)
        try:
            episode_ids = await self._track_episodes(evaluations)
        except Exception:
            # Episodes are analytics: never let them block storing evaluations or alerting.
            log.exception("episode_tracking_failed")
            episode_ids = None
        await self._quarantine_persistent_unverified()
        await self._announce_quarantines()
        links = [*(episode_ids or [None] * len(evaluations)), *[None] * len(parked_evaluations)]
        evaluations = [*evaluations, *parked_evaluations]
        ids = await self._repos.evaluations.add_evaluations(evaluations, links)
        alerts = 0
        for evaluation_id, evaluation, episode_id in zip(ids, evaluations, links, strict=True):
            if not evaluation.is_alertable or self._is_quarantined(evaluation.route_key):
                continue
            if episode_id is None:
                sent = await self._alert(evaluation_id, evaluation)  # no episode: route cooldown
            else:
                sent = await self._alert_episode(evaluation_id, evaluation, episode_id)
            alerts += sent
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
            streamed_books=self._streamed_books,
            quarantined=len(parked),
        )
        log.info(
            "sweep_done",
            exchanges_ok=result.exchanges_ok,
            routes=result.routes,
            candidates=result.candidates,
            evaluations=result.evaluations,
            alerts=result.alerts,
            timed_out=result.timed_out,
            streamed_books=result.streamed_books,
            quarantined=result.quarantined,
            active_streams=self._streams.active if self._streams is not None else 0,
        )
        return result

    async def _track_episodes(
        self, evaluations: Sequence[SpreadEvaluation]
    ) -> list[int | None] | None:
        """Close lapsed episodes, open/extend episodes of qualifying evaluations."""
        if self._episodes is None:
            return None
        await self._announce_closed(await self._episodes.close_expired())
        observed = await self._episodes.observe(evaluations)
        for episode in observed.opened:
            task = asyncio.create_task(self._check_latency(episode))
            self._latency_checks.add(task)
            task.add_done_callback(self._latency_checks.discard)
        return observed.episode_ids

    # ------------------------------------------------------------------ quarantine

    def _is_quarantined(self, key: str) -> bool:
        return self._quarantine is not None and self._quarantine.get(key) is not None

    async def _refresh_quarantine(self) -> dict[str, RouteQuarantine]:
        if self._quarantine is None:
            return {}
        try:
            return await self._quarantine.refresh()
        except Exception:
            # Fail open: alerts stay gated by the verified-transfer policy either way.
            log.exception("quarantine_refresh_failed")
            return self._quarantine.active

    async def _start_quarantine(
        self,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        reason: QuarantineReason,
        note: str,
    ) -> None:
        if self._quarantine is None:
            return
        key = route_key(symbol, buy_exchange, sell_exchange)
        try:
            started = await self._quarantine.quarantine(
                symbol, buy_exchange, sell_exchange, reason, note
            )
        except Exception:
            log.exception("quarantine_failed", route=key)
            return
        if started is None:
            return
        self._new_quarantines.append(started)  # announced even if closing the episode fails
        if self._episodes is None:
            return
        try:
            closed = await self._episodes.close_route(key, EpisodeCloseReason.QUARANTINED)
            await self._announce_closed([closed] if closed is not None else [])
        except Exception:
            log.exception("quarantine_episode_close_failed", route=key)

    async def _announce_quarantines(self) -> None:
        """One message per sweep; a route re-quarantined for the same reason is announced at
        most once per :data:`QUARANTINE_ANNOUNCE_COOLDOWN_S`."""
        started, self._new_quarantines = self._new_quarantines, []
        routes: list[QuarantinedRoute] = []
        for quarantine in started:
            announce_key = f"quarantine-announced:{quarantine.route_key}:{quarantine.reason}"
            try:
                fresh = await self._cooldowns.acquire(announce_key, QUARANTINE_ANNOUNCE_COOLDOWN_S)
            except Exception:
                log.exception("quarantine_announce_check_failed", route=quarantine.route_key)
                fresh = True
            if fresh:
                routes.append(
                    QuarantinedRoute(
                        symbol=quarantine.symbol,
                        buy_exchange=quarantine.buy_exchange,
                        sell_exchange=quarantine.sell_exchange,
                        reason=quarantine.reason.value,
                        note=quarantine.note,
                    )
                )
        if routes:
            await self._emit(
                RoutesQuarantined(routes=tuple(routes), duration_h=started[0].ttl_ms // 3_600_000)
            )

    async def _quarantine_unavailable(self, evaluations: Sequence[SpreadEvaluation]) -> None:
        """A route whose asset cannot be moved is dead right away."""
        for evaluation in evaluations:
            if evaluation.status is EvaluationStatus.TRANSFER_UNAVAILABLE:
                await self._start_quarantine(
                    evaluation.symbol,
                    evaluation.buy_exchange,
                    evaluation.sell_exchange,
                    QuarantineReason.TRANSFER_UNAVAILABLE,
                    evaluation.transfer.note,
                )

    async def _quarantine_persistent_unverified(self) -> None:
        """The ZIL/ONE pattern: a spread that persists while the transfer is unverified."""
        if self._quarantine is None or self._episodes is None:
            return
        open_episodes = self._episodes.open_episodes.values()
        for episode in self._quarantine.persistent_unverified(open_episodes):
            since = episode.unverified_since_ms or episode.opened_at_ms
            minutes = (self._clock.now_ms() - since) // 60_000
            await self._start_quarantine(
                episode.symbol,
                episode.buy_exchange,
                episode.sell_exchange,
                QuarantineReason.UNVERIFIED_PERSISTENT,
                f"spread persisted {minutes} min with transfer {episode.transfer_status.value}",
            )

    async def _lift_verified_quarantines(self) -> None:
        """After a metadata refresh, lift quarantines whose transfer path is now verified."""
        if self._quarantine is None:
            return
        try:
            await self._quarantine.refresh()
            await self._quarantine.lift_where(
                lambda q: (
                    self._route_transfer(q.symbol, q.buy_exchange, q.sell_exchange).status
                    is TransferStatus.VERIFIED
                )
            )
        except Exception:
            log.exception("quarantine_lift_failed")

    def _route_transfer(self, symbol: str, buy_exchange: str, sell_exchange: str) -> TransferQuote:
        buy_market = self._universe.market(buy_exchange, symbol)
        sell_market = self._universe.market(sell_exchange, symbol)
        if buy_market is None or sell_market is None:
            return TransferQuote(TransferStatus.UNKNOWN, note="market not scanned")
        return select_transfer_route(
            self._universe.transfer_info(buy_exchange, buy_market.base),
            self._universe.transfer_info(sell_exchange, sell_market.base),
        )

    def _parked_evaluations(
        self, parked: list[RouteQuote], quarantined: Mapping[str, RouteQuarantine]
    ) -> list[SpreadEvaluation]:
        """Ticker-level records of quarantined routes, at most once a minute per route."""
        now = self._clock.now_ms()
        self._parked_at = {
            k: t for k, t in self._parked_at.items() if now - t < PARKED_RECORD_INTERVAL_MS
        }
        records: list[SpreadEvaluation] = []
        for route in self._finder.select(parked, self._config.max_candidates_per_sweep):
            key = _route_key(route)
            if key in self._parked_at:
                continue
            if evaluation := self._quarantined_evaluation(route, quarantined[key]):
                records.append(evaluation)
                self._parked_at[key] = now
        return records

    def _quarantined_evaluation(
        self, route: RouteQuote, quarantine: RouteQuarantine
    ) -> SpreadEvaluation | None:
        """Ticker-level record of a quarantined route (no order books are fetched)."""
        buy_market = self._universe.market(route.buy_exchange, route.symbol)
        sell_market = self._universe.market(route.sell_exchange, route.symbol)
        if buy_market is None or sell_market is None:
            return None
        return SpreadEvaluation(
            symbol=route.symbol,
            base=buy_market.base,
            quote=buy_market.quote,
            buy_exchange=route.buy_exchange,
            sell_exchange=route.sell_exchange,
            notional_usd=self._estimator.config.reference_notional_usd,
            status=EvaluationStatus.QUARANTINED,
            transfer=self._route_transfer(route.symbol, route.buy_exchange, route.sell_exchange),
            buy_book_age_ms=0,
            sell_book_age_ms=0,
            evaluated_at_ms=self._clock.now_ms(),
            gross_spread_pct=route.gross_spread_pct,
            reason=f"route quarantined: {quarantine.reason.value}",
            fees_estimated=buy_market.taker_fee_is_default or sell_market.taker_fee_is_default,
        )

    # ------------------------------------------------------------------ episodes

    async def _announce_closed(self, closed: Sequence[OpportunityEpisode]) -> None:
        """Tell the user how alerted episodes ended (unalerted ones stay silent)."""
        for episode in closed:
            if not episode.alerted or episode.close_reason is None:
                continue
            await self._emit(
                EpisodeClosed(
                    symbol=episode.symbol,
                    buy_exchange=episode.buy_exchange,
                    sell_exchange=episode.sell_exchange,
                    reason=episode.close_reason.value,
                    duration_s=episode.duration_ms // 1000,
                    peak_net_usd=decimal_str(episode.peak_net_usd),
                    peak_net_pct=decimal_str(episode.peak_net_pct),
                    evaluations=episode.evaluations,
                    realerts=episode.realerts,
                    survived_latency=episode.survived_latency,
                )
            )

    async def _alert_episode(
        self, evaluation_id: int, evaluation: SpreadEvaluation, episode_id: int
    ) -> bool:
        """One alert per episode, plus re-alerts on growth (see ``OpportunityEpisode``)."""
        if self._episodes is None or evaluation.breakdown is None:  # pragma: no cover
            return False
        episode = self._episodes.get(evaluation.route_key)
        if episode is None or episode.id != episode_id:
            return False  # closed or replaced meanwhile
        net = evaluation.breakdown.net_profit_usd
        kind = episode.alert_kind(net, self._config.realert_growth_pct)
        if kind is None:
            return False
        floor_key = f"alert:{evaluation.route_key}"
        # The route cooldown is a floor between FIRST alerts: a flapping route whose episodes
        # close and reopen does not alert again within it. Re-alerts are bounded by growth.
        if kind is AlertKind.FIRST and not await self._cooldowns.acquire(
            floor_key, self._config.alert_cooldown_s
        ):
            return False
        realert = episode.realerts + 1 if kind is AlertKind.REALERT else 0
        dedup_key = f"alert:episode:{episode_id}:{realert}"
        if not await self._cooldowns.acquire(dedup_key, EPISODE_ALERT_KEY_TTL_S):
            return False
        context = AlertContext(
            episode_id=episode_id,
            realert=realert,
            previous_net_usd=decimal_str(episode.alerted_net_usd)
            if kind is AlertKind.REALERT and episode.alerted_net_usd is not None
            else None,
        )
        try:
            await self._dispatcher.dispatch_opportunity(evaluation_id, context)
        except Exception:
            log.exception("alert_dispatch_failed", evaluation_id=evaluation_id)
            with contextlib.suppress(Exception):
                await self._cooldowns.release(dedup_key)
                if kind is AlertKind.FIRST:
                    await self._cooldowns.release(floor_key)
            return False
        try:
            await self._episodes.update(episode.mark_alerted(self._clock.now_ms(), net, kind))
        except Exception:  # the Redis dedup key still prevents a duplicate alert
            log.exception("episode_alert_mark_failed", episode_id=episode_id)
        log.info(
            "opportunity_alerted",
            route=evaluation.route_key,
            episode_id=episode_id,
            kind=kind.value,
            net_profit_usd=str(net),
            evaluation_id=evaluation_id,
        )
        return True

    async def _check_latency(self, episode: OpportunityEpisode) -> None:
        """Did the opportunity survive the simulated execution latency (REST books)?"""
        if self._episodes is None:  # pragma: no cover - only scheduled with a tracker
            return
        try:
            await asyncio.sleep(self._config.latency_check_ms / 1000)
            buy, sell = await asyncio.gather(
                self._fetch_book(episode.buy_exchange, episode.symbol, allow_stream=False),
                self._fetch_book(episode.sell_exchange, episode.symbol, allow_stream=False),
            )
            if buy is None or sell is None:
                log.info("latency_check_unavailable", route=episode.route_key)
                return
            evaluation = self._evaluate(buy, sell)
            survived = evaluation is not None and evaluation.meets_thresholds
            if episode.id is not None:
                await self._episodes.record_latency(episode.route_key, episode.id, survived)
            log.info("latency_checked", route=episode.route_key, survived=survived)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("latency_check_failed", route=episode.route_key)

    async def _update_streams(self, evaluations: Sequence[SpreadEvaluation]) -> None:
        """Keep streaming both legs of every route that just showed a positive net spread.

        Routes that can never alert (unverified transfer while verification is required) do
        not take stream slots from alertable ones.
        """
        if self._streams is None:
            return
        require_verified = self._estimator.config.require_verified_transfer
        for evaluation in evaluations:
            breakdown = evaluation.breakdown
            if require_verified and not evaluation.transfer_verified:
                continue
            if breakdown is not None and breakdown.net_profit_usd > 0:
                self._streams.mark_hot(evaluation.buy_exchange, evaluation.symbol)
                self._streams.mark_hot(evaluation.sell_exchange, evaluation.symbol)
        await self._streams.prune()

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
            evaluation = self._evaluate(buy_book, sell_book)
            if (
                evaluation is not None
                and evaluation.is_alertable
                and (buy_book.streamed or sell_book.streamed)
            ):
                return await self._confirm_with_rest(route, buy_book, sell_book)
            return evaluation

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

    async def _confirm_with_rest(
        self, route: RouteQuote, buy_book: OrderBook, sell_book: OrderBook
    ) -> SpreadEvaluation | None:
        """Re-evaluate an alertable route on REST snapshots for its WebSocket-sourced legs.

        Incremental WS books can silently miss a delta (some ccxt streams have no gap
        detection) and keep a phantom level; an alert is only ever based on REST data.
        """
        buy, sell = await asyncio.gather(
            self._rest_book_for(buy_book),
            self._rest_book_for(sell_book),
        )
        if buy is None or sell is None:
            log.info("ws_confirmation_failed", route=route.symbol)
            return None
        confirmed = self._evaluate(buy, sell)
        log.info(
            "ws_opportunity_rechecked",
            route=route.symbol,
            confirmed=confirmed is not None and confirmed.is_alertable,
        )
        return confirmed

    async def _rest_book_for(self, book: OrderBook) -> OrderBook | None:
        if not book.streamed:
            return book
        return await self._fetch_book(book.exchange, book.symbol, allow_stream=False)

    async def _fetch_book(
        self, exchange: str, symbol: str, *, allow_stream: bool = True
    ) -> OrderBook | None:
        if self._health.is_paused(exchange, self._clock.now_ms()):
            return None
        if (
            allow_stream
            and self._streams is not None
            and (book := self._streams.fresh_book(exchange, symbol))
        ):
            self._streamed_books += 1
            return book
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

    def _evaluate(self, buy_book: OrderBook, sell_book: OrderBook) -> SpreadEvaluation | None:
        buy_market = self._universe.market(buy_book.exchange, buy_book.symbol)
        sell_market = self._universe.market(sell_book.exchange, sell_book.symbol)
        if buy_market is None or sell_market is None:
            return None
        transfer = self._route_transfer(buy_book.symbol, buy_book.exchange, sell_book.exchange)
        try:
            return self._estimator.evaluate(
                buy_book=buy_book,
                sell_book=sell_book,
                buy_market=buy_market,
                sell_market=sell_market,
                transfer=transfer,
            )
        except (ValueError, ArithmeticError, DataValidationError):
            log.exception("evaluation_failed", route=buy_book.symbol)
            return None

    async def _emit(self, event: SystemEvent) -> None:
        try:
            await self._dispatcher.dispatch_event(event)
        except Exception:
            log.exception("event_dispatch_failed", kind=event.kind)


def _route_key(route: RouteQuote) -> str:
    return route_key(route.symbol, route.buy_exchange, route.sell_exchange)
