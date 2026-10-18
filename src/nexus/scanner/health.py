"""Per-exchange health tracking with failure thresholds, hysteresis and rate-limit pauses."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.domain.events import ExchangeDown, ExchangeRecovered, SystemEvent


@dataclass(slots=True)
class _State:
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    down_since_ms: int | None = None
    paused_until_ms: int = 0


class ExchangeHealthTracker:
    """Decides when to report an exchange as down/recovered and when to pause it.

    Failures are expected to be recorded at most once per exchange per sweep (ticker fetch);
    order-book rate limits only :meth:`pause` the exchange. A recovery is announced only
    after ``recover_after_successes`` consecutive successes, to avoid down/up flapping.
    """

    def __init__(
        self,
        *,
        down_after_failures: int,
        rate_limit_backoff_ms: int,
        recover_after_successes: int = 2,
    ) -> None:
        self._down_after = down_after_failures
        self._backoff_ms = rate_limit_backoff_ms
        self._recover_after = recover_after_successes
        self._states: dict[str, _State] = {}

    def _state(self, exchange: str) -> _State:
        return self._states.setdefault(exchange, _State())

    def is_paused(self, exchange: str, now_ms: int) -> bool:
        """True while the exchange is in rate-limit backoff."""
        return self._state(exchange).paused_until_ms > now_ms

    def pause(self, exchange: str, now_ms: int) -> None:
        """Start (or extend) a rate-limit pause without counting a failed sweep."""
        state = self._state(exchange)
        state.paused_until_ms = max(state.paused_until_ms, now_ms + self._backoff_ms)

    def is_down(self, exchange: str) -> bool:
        """True after a down event until recovery."""
        return self._state(exchange).down_since_ms is not None

    def record_success(self, exchange: str, now_ms: int) -> SystemEvent | None:
        """Register a successful sweep; returns a recovery event when it is confirmed."""
        state = self._state(exchange)
        state.consecutive_failures = 0
        state.consecutive_successes += 1
        if state.down_since_ms is None or state.consecutive_successes < self._recover_after:
            return None
        downtime_s = max(0, (now_ms - state.down_since_ms) // 1000)
        state.down_since_ms = None
        return ExchangeRecovered(exchange=exchange, downtime_s=downtime_s)

    def record_failure(
        self, exchange: str, now_ms: int, error: str, *, rate_limited: bool = False
    ) -> SystemEvent | None:
        """Register a failed sweep; returns a down event when the threshold is crossed."""
        state = self._state(exchange)
        state.consecutive_failures += 1
        state.consecutive_successes = 0
        if rate_limited:
            self.pause(exchange, now_ms)
        if state.down_since_ms is None and state.consecutive_failures >= self._down_after:
            state.down_since_ms = now_ms
            return ExchangeDown(
                exchange=exchange, error=error, consecutive_failures=state.consecutive_failures
            )
        return None
