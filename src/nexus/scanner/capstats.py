"""Hourly per-set cap-binding counters (GO report: is the candidate cap distorting a set?).

Counters are buffered in memory and flushed additively every few minutes, so a sweep never
waits for the database; a crash loses at most one flush interval of counters.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import structlog

from nexus.engine.candidates import SetSweepStats
from nexus.interfaces.repositories import CapStatsDelta, IPaperRepository

log = structlog.get_logger(__name__)

HOUR_MS = 3_600_000
FLUSH_INTERVAL_MS = 5 * 60_000


class CapStatsBuffer:
    """Accumulates sweep / excluded-alert counters per ``(set, hour)``."""

    def __init__(
        self, repository: IPaperRepository, flush_interval_ms: int = FLUSH_INTERVAL_MS
    ) -> None:
        self._repo = repository
        self._interval = flush_interval_ms
        self._buckets: dict[tuple[str, int], CapStatsDelta] = {}
        self._last_flush_ms: int | None = None

    def add_sweep(self, now_ms: int, stats: Mapping[str, SetSweepStats]) -> None:
        """One sweep: a counted sweep per set, cap-bound when routes were cut."""
        for pid, st in stats.items():
            cur = self._bucket(pid, now_ms)
            self._buckets[(pid, cur.hour_ms)] = CapStatsDelta(
                pid,
                cur.hour_ms,
                cur.sweeps + 1,
                cur.sweeps_cap_bound + (1 if st.cap_bound else 0),
                cur.dropped_routes + st.dropped,
                cur.alerts_cap_excluded,
            )

    def add_alert_excluded(self, now_ms: int, portfolio_ids: Collection[str]) -> None:
        """An alert on a route that was inside these sets but outside their top-N this sweep."""
        for pid in portfolio_ids:
            cur = self._bucket(pid, now_ms)
            self._buckets[(pid, cur.hour_ms)] = CapStatsDelta(
                pid,
                cur.hour_ms,
                cur.sweeps,
                cur.sweeps_cap_bound,
                cur.dropped_routes,
                cur.alerts_cap_excluded + 1,
            )

    async def flush(self, now_ms: int, *, force: bool = False) -> None:
        """Write the buffered counters (failures keep them for the next try)."""
        if self._last_flush_ms is None:
            self._last_flush_ms = now_ms
        if not self._buckets or (not force and now_ms - self._last_flush_ms < self._interval):
            return
        pending, self._buckets = self._buckets, {}
        self._last_flush_ms = now_ms
        try:
            await self._repo.add_cap_stats(list(pending.values()))
        except Exception:
            log.exception("paper_cap_stats_flush_failed")
            for key, lost in pending.items():
                cur = self._buckets.get(key)
                self._buckets[key] = lost if cur is None else _merge(lost, cur)

    def _bucket(self, pid: str, now_ms: int) -> CapStatsDelta:
        hour = now_ms - now_ms % HOUR_MS
        return self._buckets.get((pid, hour)) or CapStatsDelta(pid, hour)


def _merge(a: CapStatsDelta, b: CapStatsDelta) -> CapStatsDelta:
    return CapStatsDelta(
        a.portfolio_id,
        a.hour_ms,
        a.sweeps + b.sweeps,
        a.sweeps_cap_bound + b.sweeps_cap_bound,
        a.dropped_routes + b.dropped_routes,
        a.alerts_cap_excluded + b.alerts_cap_excluded,
    )
