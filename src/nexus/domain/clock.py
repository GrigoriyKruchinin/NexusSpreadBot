"""Injectable time source (keeps time-dependent logic deterministic in tests)."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Provides the current wall-clock time in epoch milliseconds."""

    def now_ms(self) -> int:
        """Current epoch time in milliseconds."""
        ...


class SystemClock:
    """Real wall clock."""

    def now_ms(self) -> int:
        """Current epoch time in milliseconds."""
        return time.time_ns() // 1_000_000
