"""Opportunity episode tracking (scanner-side state, persisted through a repository)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import structlog

from nexus.domain.clock import Clock
from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.spread import SpreadEvaluation
from nexus.interfaces.repositories import IEpisodeRepository

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ObservedEvaluations:
    """Result of :meth:`EpisodeTracker.observe`."""

    episode_ids: list[int | None]
    """Episode of each observed evaluation (``None`` = below the thresholds), input order."""
    opened: list[OpportunityEpisode]
    """Episodes opened by this batch."""


class EpisodeTracker:
    """Opens, extends and closes episodes; at most one open episode per route.

    A qualifying evaluation (``meets_thresholds``: profitable, verified or not) opens or
    extends its route's episode. An episode closes once ``close_gap_ms`` passes without one.
    """

    def __init__(self, repository: IEpisodeRepository, *, close_gap_ms: int, clock: Clock) -> None:
        """Create the tracker; call :meth:`start` before the first observation."""
        if close_gap_ms <= 0:
            msg = "close_gap_ms must be positive"
            raise ValueError(msg)
        self._repo = repository
        self._gap_ms = close_gap_ms
        self._clock = clock
        self._open: dict[str, OpportunityEpisode] = {}

    @property
    def open_episodes(self) -> dict[str, OpportunityEpisode]:
        """Open episodes by route key (copy)."""
        return dict(self._open)

    def get(self, route_key: str) -> OpportunityEpisode | None:
        """Open episode of a route."""
        return self._open.get(route_key)

    async def start(self) -> list[OpportunityEpisode]:
        """Resume after a restart: lapsed open episodes are closed with ``restart``, the rest
        continue. Returns the episodes closed now."""
        now = self._clock.now_ms()
        closed: list[OpportunityEpisode] = []
        self._open.clear()
        for episode in await self._repo.list_open():
            if episode.expired(now, self._gap_ms):
                closed.append(episode.close(self._closed_at(episode), EpisodeCloseReason.RESTART))
            else:
                self._open[episode.route_key] = episode
        await self._repo.save(closed)
        if closed or self._open:
            log.info("episodes_resumed", closed=len(closed), resumed=len(self._open))
        return closed

    async def close_expired(self) -> list[OpportunityEpisode]:
        """Close every open episode whose gap elapsed; returns them."""
        now = self._clock.now_ms()
        expired = [e for e in self._open.values() if e.expired(now, self._gap_ms)]
        closed = [e.close(self._closed_at(e), EpisodeCloseReason.GAP) for e in expired]
        await self._commit_closed(closed)
        return closed

    async def close_route(
        self, route_key: str, reason: EpisodeCloseReason
    ) -> OpportunityEpisode | None:
        """Close a route's open episode now (e.g. quarantine); idempotent."""
        episode = self._open.get(route_key)
        if episode is None:
            return None
        closed = episode.close(self._clock.now_ms(), reason)
        await self._commit_closed([closed])
        return closed

    async def observe(self, evaluations: Sequence[SpreadEvaluation]) -> ObservedEvaluations:
        """Open/extend episodes for qualifying evaluations (persisted before returning)."""
        ids: list[int | None] = []
        inserted: dict[str, OpportunityEpisode] = {}
        touched: list[str] = []
        for evaluation in evaluations:
            if not evaluation.meets_thresholds or evaluation.breakdown is None:
                ids.append(None)
                continue
            key = evaluation.route_key
            current = self._open.get(key)
            if current is None:
                fresh = OpportunityEpisode.open(evaluation)
                stored = await self._repo.open(fresh)
                if stored == replace(fresh, id=stored.id):
                    episode = stored
                    inserted[key] = episode
                else:  # the route already had an open row (e.g. a lost insert reply): adopt it
                    log.warning("episode_adopted", episode_id=stored.id, route=key)
                    episode = stored.extend(evaluation)
            else:
                episode = current.extend(evaluation)
            self._open[key] = episode
            touched.append(key)
            ids.append(episode.id)
        # Save final states, except freshly inserted episodes that did not change since.
        changed = {k: self._open[k] for k in touched if self._open[k] != inserted.get(k)}
        await self._repo.save(list(changed.values()))
        opened = list(inserted.values())
        for episode in opened:
            log.info(
                "episode_opened",
                episode_id=episode.id,
                route=episode.route_key,
                net_usd=str(episode.first_net_usd),
                transfer=episode.transfer_status.value,
            )
        return ObservedEvaluations(episode_ids=ids, opened=opened)

    async def update(self, episode: OpportunityEpisode) -> None:
        """Persist a changed open episode (alert bookkeeping, ...)."""
        current = self._open.get(episode.route_key)
        if current is None or current.id != episode.id:
            return  # closed or replaced meanwhile: nothing to update
        self._open[episode.route_key] = episode
        await self._repo.save([episode])

    async def record_latency(self, route_key: str, episode_id: int, survived: bool) -> None:
        """Store the latency re-check result (memory + a single-column DB update)."""
        current = self._open.get(route_key)
        if current is None or current.id != episode_id:
            return
        self._open[route_key] = replace(current, survived_latency=survived)
        await self._repo.set_survived_latency(episode_id, survived)

    def _closed_at(self, episode: OpportunityEpisode) -> int:
        """A lapsed episode ended when its gap ran out, not when the lapse was noticed
        (e.g. after hours of downtime)."""
        return min(self._clock.now_ms(), episode.last_seen_at_ms + self._gap_ms)

    async def _commit_closed(self, closed: Sequence[OpportunityEpisode]) -> None:
        if not closed:
            return
        await self._repo.save(closed)
        for episode in closed:
            self._open.pop(episode.route_key, None)
            log.info(
                "episode_closed",
                episode_id=episode.id,
                route=episode.route_key,
                reason=episode.close_reason.value if episode.close_reason else None,
                duration_ms=episode.duration_ms,
                peak_net_usd=str(episode.peak_net_usd),
                evaluations=episode.evaluations,
                survived_latency=episode.survived_latency,
            )
