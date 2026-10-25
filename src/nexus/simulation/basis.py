"""Relative-basis history buffer and kline volatility statistics (HT spec 5, 5.1). Pure.

``x = (bid_B - bid_H) / mid_H`` is stored as a fixed-point int64 (``x * 1e8``, half-even) in a ring
buffer with a parallel array of sample times. Samples may be missing, so windows and lag pairs are
taken by time, never by index, and nothing is imputed.
"""

from __future__ import annotations

import itertools
from array import array
from bisect import bisect_left
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import median
from typing import Final

from nexus.domain.models import ZERO
from nexus.domain.perp import MarkKline

SCALE: Final = Decimal(10) ** 8
CAPACITY: Final = 720
"""6 h of 30 s samples."""
WINDOW_MS: Final = 6 * 3_600_000
MIN_SAMPLES: Final = 60
PAIR_TOLERANCE_MS: Final = 15_000
STD_FLOOR: Final = Decimal("0.0001")
MINUTE_MS: Final = 60_000
BYTES_PER_SAMPLE: Final = 16
"""One int64 value + one int64 time."""

BasisKey = tuple[str, str, str]
"""``(coin, spot venue B, hedge venue H)``."""


def to_fixed(x: Decimal) -> int:
    """Relative basis -> integer in units of 1e-8 (round half even)."""
    return int((x * SCALE).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def from_fixed(value: int) -> Decimal:
    """Inverse of :func:`to_fixed`."""
    return Decimal(value) / SCALE


@dataclass(frozen=True, slots=True)
class BasisStats:
    """Window statistics at one pre-check (relative basis units)."""

    samples: int
    pairs: int
    median: Decimal
    std: Decimal
    lag_std: Decimal | None
    """Std of ``x(t + lag) - x(t)`` over matched pairs (``None`` below 2 pairs)."""
    warmup: bool
    """True when the window holds < min samples or < min lag pairs."""

    def zscore(self, x_now: Decimal, std_floor: Decimal = STD_FLOOR) -> Decimal:
        """``(x_now - median) / max(std, floor)``."""
        return (x_now - self.median) / max(self.std, std_floor)


def _std(values: Sequence[Decimal]) -> Decimal:
    """Sample standard deviation (n - 1); zero for fewer than two values."""
    n = len(values)
    if n < 2:
        return ZERO
    mean = sum(values, ZERO) / n
    return (sum(((v - mean) ** 2 for v in values), ZERO) / (n - 1)).sqrt()


class BasisBuffer:
    """Fixed-capacity ring of ``(time_ms, fixed-point x)`` samples, times strictly increasing."""

    __slots__ = ("_capacity", "_count", "_head", "_times", "_values")

    def __init__(self, capacity: int = CAPACITY) -> None:
        if capacity < 2:
            msg = "capacity must be >= 2"
            raise ValueError(msg)
        self._capacity = capacity
        self._times = array("q", bytes(8 * capacity))
        self._values = array("q", bytes(8 * capacity))
        self._head = 0  # next write slot
        self._count = 0

    def __len__(self) -> int:
        return self._count

    @property
    def nbytes(self) -> int:
        """Bytes held by the two arrays (constant after construction)."""
        return (self._times.itemsize + self._values.itemsize) * self._capacity

    def _last_time(self) -> int | None:
        return self._times[(self._head - 1) % self._capacity] if self._count else None

    def add(self, time_ms: int, x: Decimal) -> bool:
        """Append a sample; out-of-order or duplicate times are rejected (returns False)."""
        last = self._last_time()
        if last is not None and time_ms <= last:
            return False
        self._times[self._head] = time_ms
        self._values[self._head] = to_fixed(x)
        self._head = (self._head + 1) % self._capacity
        self._count = min(self._count + 1, self._capacity)
        return True

    def samples(self) -> tuple[list[int], list[int]]:
        """``(times, fixed values)`` in chronological order."""
        start = (self._head - self._count) % self._capacity
        idx = [(start + i) % self._capacity for i in range(self._count)]
        return [self._times[i] for i in idx], [self._values[i] for i in idx]

    def stats(
        self,
        now_ms: int,
        lag_ms: int,
        *,
        window_ms: int = WINDOW_MS,
        min_samples: int = MIN_SAMPLES,
        pair_tolerance_ms: int = PAIR_TOLERANCE_MS,
    ) -> BasisStats | None:
        """Median/std over ``(now - window, now]`` and lag-pair std; ``None`` when empty.

        A pair ``(t, t')`` uses the sample nearest to ``t + lag`` if it lies within the tolerance
        and is a different sample; missing partners are skipped, never interpolated.
        """
        times, fixed = self.samples()
        lo = bisect_left(times, now_ms - window_ms + 1)
        hi = bisect_left(times, now_ms + 1)
        w_times, w_fixed = times[lo:hi], fixed[lo:hi]
        if not w_times:
            return None
        values = [from_fixed(v) for v in w_fixed]
        diffs: list[Decimal] = []
        for i, t in enumerate(w_times):
            target = t + lag_ms
            if target > w_times[-1] + pair_tolerance_ms:
                break
            j = bisect_left(w_times, target)
            best = min(
                (k for k in (j - 1, j) if 0 <= k < len(w_times)),
                key=lambda k: abs(w_times[k] - target),
            )
            if best != i and abs(w_times[best] - target) <= pair_tolerance_ms:
                diffs.append(values[best] - values[i])
        n, pairs = len(values), len(diffs)
        return BasisStats(
            samples=n,
            pairs=pairs,
            median=median(values),
            std=_std(values),
            lag_std=_std(diffs) if pairs >= 2 else None,
            warmup=n < min_samples or pairs < min_samples,
        )


class BasisStore:
    """One buffer per ``(coin, B, H)`` key, created lazily."""

    def __init__(self, capacity: int = CAPACITY) -> None:
        self._capacity = capacity
        self._buffers: dict[BasisKey, BasisBuffer] = {}

    def __len__(self) -> int:
        return len(self._buffers)

    def add(self, key: BasisKey, time_ms: int, x: Decimal) -> bool:
        """Record one sample for ``key``."""
        buf = self._buffers.get(key)
        if buf is None:
            buf = self._buffers[key] = BasisBuffer(self._capacity)
        return buf.add(time_ms, x)

    def get(self, key: BasisKey) -> BasisBuffer | None:
        """Buffer of ``key`` if any sample was ever stored."""
        return self._buffers.get(key)

    @property
    def nbytes(self) -> int:
        """Total array bytes: ``keys * capacity * 16``."""
        return sum(b.nbytes for b in self._buffers.values())


# ------------------------------------------------------------------ kline statistics


def sigma_1m(klines: Sequence[MarkKline]) -> Decimal | None:
    """Std of 1 m log returns of closes, over consecutive-minute pairs only (gaps not imputed).

    ``None`` when fewer than two returns exist.
    """
    returns: list[Decimal] = []
    ordered = sorted(klines, key=lambda k: k.open_ms)
    for prev, cur in itertools.pairwise(ordered):
        if cur.open_ms - prev.open_ms == MINUTE_MS:
            returns.append((cur.close / prev.close).ln())
    return _std(returns) if len(returns) >= 2 else None


def max_rise(klines: Sequence[MarkKline], window_min: int) -> Decimal | None:
    """Largest ``high_j / open_i - 1`` for candles ``j`` within ``window_min`` minutes after ``i``.

    Only candles that exist are used (missing minutes are skipped, not filled); ``None`` for no
    data. Clamped at 0 (a falling market has no rise).
    """
    ordered = sorted(klines, key=lambda k: k.open_ms)
    if not ordered:
        return None
    span = window_min * MINUTE_MS
    best = ZERO
    # Sliding maximum of highs over [t_i, t_i + span], scanning from the right. The deque keeps
    # time-ascending candidates with strictly increasing highs: the maximum is the last element.
    window: deque[MarkKline] = deque()
    for cur in reversed(ordered):
        while window and window[0].high <= cur.high:
            window.popleft()  # later and not higher: dominated by ``cur``
        window.appendleft(cur)
        while window[-1].open_ms > cur.open_ms + span:
            window.pop()
        best = max(best, window[-1].high / cur.open - 1)
    return best
