"""Automatic quarantine of dead routes (decisions + shared store + history mirror)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import structlog

from nexus.domain.clock import Clock
from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.quarantine import QuarantineReason, RouteQuarantine
from nexus.interfaces.coordination import IQuarantineStore
from nexus.interfaces.repositories import IQuarantineRepository

log = structlog.get_logger(__name__)


class QuarantineManager:
    """Keeps a per-sweep snapshot of active quarantines and applies the quarantine rules.

    * An episode open for ``persist_ms`` without a ``VERIFIED`` transfer path quarantines
      its route: a spread that persists while nobody can move the coin is a dead route.
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
    ) -> None:
        """Create the manager (``persist_ms``/``ttl_ms`` must be positive)."""
        if persist_ms <= 0 or ttl_ms <= 0:
            msg = "persist_ms and ttl_ms must be positive"
            raise ValueError(msg)
        self._store = store
        self._repo = repository
        self._persist_ms = persist_ms
        self._ttl_ms = ttl_ms
        self._clock = clock
        self._active: dict[str, RouteQuarantine] = {}

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

    def persistent_unverified(
        self, episodes: Iterable[OpportunityEpisode]
    ) -> list[OpportunityEpisode]:
        """Open episodes whose transfer path has been unverified for ``persist_ms``.

        Measured from when the path *became* unverified, so a long verified episode is not
        quarantined the moment one metadata refresh fails.
        """
        now = self._clock.now_ms()
        return [
            e
            for e in episodes
            if e.is_open
            and e.unverified_since_ms is not None
            and now - e.unverified_since_ms >= self._persist_ms
            and e.route_key not in self._active
        ]

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
            if await self._store.lift(key):
                lifted.append(quarantine)
                try:
                    await self._repo.record_lift(key, now)
                except Exception:
                    log.exception("quarantine_lift_record_failed", route=key)
                log.info("route_quarantine_lifted", route=key, reason=quarantine.reason.value)
            self._active.pop(key, None)
        return lifted
