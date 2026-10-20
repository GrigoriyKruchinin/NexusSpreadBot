"""Automatic quarantine of dead routes (decisions + shared store + history mirror)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import structlog

from nexus.domain.clock import Clock
from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.interfaces.coordination import IQuarantineStore
from nexus.interfaces.repositories import IQuarantineRepository

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UnverifiedSpan:
    """Interval during which an episode qualified without a verified transfer path."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    start_ms: int
    end_ms: int
    transfer_status: str


@dataclass(frozen=True, slots=True)
class RecurringRoute:
    """A route due for quarantine and the evidence."""

    span: UnverifiedSpan
    """Its latest unverified interval (route identity and transfer status)."""
    unverified_ms: int
    episodes: int


class QuarantineManager:
    """Keeps a per-sweep snapshot of active quarantines and applies the quarantine rules.

    * A route whose spread keeps coming back without a ``VERIFIED`` transfer path is dead:
      within ``window_ms`` its unverified episodes add up to ``persist_ms`` or number at
      least ``max_episodes`` (one long episode, or a flapping one).
    * A ``TRANSFER_UNAVAILABLE`` evaluation quarantines its route immediately.
    * A quarantine lifts early when the route's transfer path turns ``VERIFIED``.

    The store (Redis) is the source of truth; the repository keeps the history for reports.
    """

    def __init__(
        self,
        store: IQuarantineStore,
        repository: IQuarantineRepository,
        *,
        persist_ms: int,
        ttl_ms: int,
        clock: Clock,
        window_ms: int = 6 * 3_600_000,
        max_episodes: int = 5,
    ) -> None:
        """Create the manager (durations and ``max_episodes`` must be positive)."""
        if min(persist_ms, ttl_ms, window_ms, max_episodes) <= 0:
            msg = "persist_ms, ttl_ms, window_ms and max_episodes must be positive"
            raise ValueError(msg)
        if window_ms < persist_ms:
            msg = "the recurrence window must not be shorter than persist_ms"
            raise ValueError(msg)
        self._store = store
        self._repo = repository
        self._persist_ms = persist_ms
        self._ttl_ms = ttl_ms
        self._clock = clock
        self._window_ms = window_ms
        self._max_episodes = max_episodes
        self._active: dict[str, RouteQuarantine] = {}
        self._spans: dict[str, dict[int, UnverifiedSpan]] = {}
        """route key -> episode id -> its unverified interval (recurrence history)."""

    @property
    def active(self) -> dict[str, RouteQuarantine]:
        """Snapshot of unexpired quarantines (copy; expiry checked against the clock)."""
        now = self._clock.now_ms()
        self._active = {k: q for k, q in self._active.items() if q.expires_at_ms > now}
        return dict(self._active)

    def get(self, route_key: str) -> RouteQuarantine | None:
        """Active quarantine of a route (snapshot)."""
        return self._active.get(route_key)

    async def refresh(self) -> dict[str, RouteQuarantine]:
        """Reload the snapshot from the shared store (expired entries disappear)."""
        self._active = await self._store.active()
        return dict(self._active)

    def recurring_unverified(
        self, open_episodes: Iterable[OpportunityEpisode]
    ) -> list[RecurringRoute]:
        """Routes whose unverified episodes recur or persist within the window.

        Call once per sweep with the open episodes: their unverified intervals are recorded
        (closed episodes keep their last recorded interval). A verified episode clears its
        route's history - the route is alive. Time is measured from when the transfer path
        *became* unverified, so a metadata glitch does not count a verified past against it.
        """
        now = self._clock.now_ms()
        for episode in open_episodes:
            if episode.id is None:
                continue
            if episode.unverified_since_ms is None:
                self._spans.pop(episode.route_key, None)
                continue
            self._spans.setdefault(episode.route_key, {})[episode.id] = UnverifiedSpan(
                episode.symbol,
                episode.buy_exchange,
                episode.sell_exchange,
                episode.unverified_since_ms,
                episode.last_seen_at_ms,
                episode.transfer_status.value,
            )
        due: list[RecurringRoute] = []
        horizon = now - self._window_ms
        for key in list(self._spans):
            spans = {i: s for i, s in self._spans[key].items() if s.end_ms >= horizon}
            if not spans:
                del self._spans[key]
                continue
            self._spans[key] = spans
            if key in self._active:
                continue
            total = sum(s.end_ms - max(s.start_ms, horizon) for s in spans.values())
            if total >= self._persist_ms or len(spans) >= self._max_episodes:
                last = max(spans.values(), key=lambda s: s.end_ms)
                due.append(RecurringRoute(last, total, len(spans)))
        return due

    async def quarantine(
        self,
        symbol: str,
        buy_exchange: str,
        sell_exchange: str,
        reason: QuarantineReason,
        note: str = "",
    ) -> RouteQuarantine | None:
        """Start a quarantine; returns it only when it is new (one event per start)."""
        now = self._clock.now_ms()
        quarantine = RouteQuarantine(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            reason=reason,
            started_at_ms=now,
            expires_at_ms=now + self._ttl_ms,
            note=note,
        )
        if quarantine.route_key in self._active or not await self._store.add(quarantine):
            return None
        self._active[quarantine.route_key] = quarantine
        try:
            await self._repo.record_start(quarantine)
        except Exception:  # history only: the store already enforces the quarantine
            log.exception("quarantine_record_failed", route=quarantine.route_key)
        log.info(
            "route_quarantined",
            route=quarantine.route_key,
            reason=reason.value,
            note=note[:200],
            ttl_ms=self._ttl_ms,
        )
        return quarantine

    async def lift_where(
        self, should_lift: Callable[[RouteQuarantine], bool]
    ) -> list[RouteQuarantine]:
        """Lift active quarantines matching ``should_lift`` (e.g. transfer now verified)."""
        lifted: list[RouteQuarantine] = []
        now = self._clock.now_ms()
        for key, quarantine in list(self._active.items()):
            if not should_lift(quarantine):
                continue
            self._spans.pop(key, None)  # the path is verified now: old evidence is void
            if await self._store.lift(key):
                lifted.append(quarantine)
                try:
                    await self._repo.record_lift(key, now)
                except Exception:
                    log.exception("quarantine_lift_record_failed", route=key)
                log.info("route_quarantine_lifted", route=key, reason=quarantine.reason.value)
            self._active.pop(key, None)
        return lifted
