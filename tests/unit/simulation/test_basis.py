import math
import random
from decimal import Decimal as D

import pytest

from nexus.domain.perp import MarkKline
from nexus.simulation.basis import (
    BasisBuffer,
    BasisStore,
    from_fixed,
    max_rise,
    sigma_1m,
    to_fixed,
)

STEP = 30_000


def test_fixed_point_roundtrip_and_half_even() -> None:
    assert to_fixed(D("0.00123456")) == 123456
    assert from_fixed(123456) == D("0.00123456")
    assert to_fixed(D("0.000000025")) == 2  # 2.5 -> 2 (half even)
    assert to_fixed(D("0.000000035")) == 4
    assert to_fixed(D("-0.0001")) == -10000


def _fill(buf: BasisBuffer, values: list[str], start: int = 0, step: int = STEP) -> int:
    t = start
    for v in values:
        assert buf.add(t, D(v))
        t += step
    return t


def test_rejects_out_of_order_and_duplicates() -> None:
    buf = BasisBuffer()
    assert buf.add(1000, D("0.001"))
    assert not buf.add(1000, D("0.002"))
    assert not buf.add(900, D("0.002"))
    assert len(buf) == 1


def test_median_std_hand_computed() -> None:
    buf = BasisBuffer()
    _fill(buf, ["0.001", "0.002", "0.003", "0.004", "0.010"])
    stats = buf.stats(now_ms=4 * STEP, lag_ms=STEP)
    assert stats is not None
    assert stats.samples == 5
    assert stats.median == D("0.003")
    # mean 0.004; deviations -3,-2,-1,0,6 (x1e-3); squares 9+4+1+0+36=50e-6; /4 = 12.5e-6
    assert float(stats.std) == pytest.approx(math.sqrt(12.5e-6), rel=1e-12)
    assert stats.warmup  # < 60 samples
    # pairs at lag 30 s: diffs 1,1,1,6 (x1e-3); mean 2.25; var = (1.5625*3+14.0625)/3 = 6.25e-6
    assert stats.pairs == 4
    assert stats.lag_std is not None
    assert float(stats.lag_std) == pytest.approx(math.sqrt(6.25e-6), rel=1e-12)


def test_zscore_uses_floor() -> None:
    buf = BasisBuffer()
    _fill(buf, ["0.001"] * 5)
    stats = buf.stats(4 * STEP, STEP)
    assert stats is not None
    assert stats.std == 0
    assert stats.zscore(D("0.0011")) == D("0.0001") / D("0.0001")
    assert stats.zscore(D("0.001")) == 0


def test_warmup_clears_with_60_samples_and_pairs() -> None:
    buf = BasisBuffer()
    _fill(buf, [str(D("0.001") + D(i) / 10**6) for i in range(130)])
    now = 129 * STEP
    stats = buf.stats(now, lag_ms=60 * STEP)  # 30 min lag: 70 pairs
    assert stats is not None
    assert (stats.samples, stats.pairs, stats.warmup) == (130, 70, False)
    short = buf.stats(now, lag_ms=80 * STEP)  # 50 pairs < 60
    assert short is not None
    assert short.pairs == 50
    assert short.warmup


def test_missing_samples_are_not_imputed_pairs_by_time() -> None:
    buf = BasisBuffer()
    # samples at 0, 30, 60, 120 s (gap at 90 s)
    for t, v in [(0, "0.001"), (30, "0.002"), (60, "0.003"), (120, "0.005")]:
        buf.add(t * 1000, D(v))
    stats = buf.stats(120_000, lag_ms=60_000)
    assert stats is not None
    # partners: 0->60 (d 0.002), 30->90 (nearest 60 or 120, 30 s away > 15 s: skipped),
    # 60->120 (d 0.002), 120->180 (none)
    assert stats.pairs == 2
    assert stats.lag_std == D(0)
    assert stats.samples == 4  # nothing inserted for the gap
    assert len(buf) == 4


def test_pair_tolerance_boundary() -> None:
    buf = BasisBuffer()
    buf.add(0, D("0.001"))
    buf.add(75_000, D("0.002"))  # 15 s off the 60 s target: allowed
    ok = buf.stats(75_000, 60_000)
    assert ok is not None
    assert ok.pairs == 1
    buf2 = BasisBuffer()
    buf2.add(0, D("0.001"))
    buf2.add(75_001, D("0.002"))
    far = buf2.stats(75_001, 60_000)
    assert far is not None
    assert far.pairs == 0
    assert far.lag_std is None


def test_window_is_by_time_and_ring_wraps() -> None:
    buf = BasisBuffer(capacity=10)
    _fill(buf, [f"0.00{i}" for i in range(10)], step=1000)
    assert len(buf) == 10
    buf.add(10_000, D("0.01"))  # overwrites the oldest
    assert len(buf) == 10
    times, fixed = buf.samples()
    assert times == [i * 1000 for i in range(1, 11)]
    assert fixed[-1] == to_fixed(D("0.01"))
    # window of 3.5 s ending at 10 s keeps t = 7,8,9,10 s
    stats = buf.stats(10_000, 1000, window_ms=3500)
    assert stats is not None
    assert stats.samples == 4
    assert buf.stats(100_000_000, 1000, window_ms=1000) is None
    assert BasisBuffer().stats(0, 1) is None


def test_capacity_validation() -> None:
    with pytest.raises(ValueError, match="capacity"):
        BasisBuffer(1)


def test_memory_bound_is_keys_times_720_times_16() -> None:
    store = BasisStore()
    for i in range(50):
        store.add((f"C{i}", "okx", "kucoin"), 1000, D("0.001"))
    assert len(store) == 50
    assert store.nbytes == 50 * 720 * 8 * 2
    for t in range(2000):  # far beyond capacity: memory stays constant
        store.add(("C0", "okx", "kucoin"), 2000 + t * STEP, D("0.001"))
    assert store.nbytes == 50 * 720 * 16
    buf = store.get(("C0", "okx", "kucoin"))
    assert buf is not None
    assert len(buf) == 720
    assert store.get(("X", "a", "b")) is None


def _k(minute: int, o: str, h: str, low: str, c: str) -> MarkKline:
    return MarkKline(minute * 60_000, D(o), D(h), D(low), D(c))


def test_sigma_1m_consecutive_returns_only() -> None:
    ks = [_k(0, "100", "100", "100", "100"), _k(1, "100", "101", "100", "101")]
    assert sigma_1m(ks) is None  # one return
    ks.append(_k(2, "101", "101", "100", "100"))
    s = sigma_1m(ks)
    assert s is not None
    r1, r2 = math.log(1.01), math.log(100 / 101)
    mean = (r1 + r2) / 2
    expected = math.sqrt(((r1 - mean) ** 2 + (r2 - mean) ** 2) / 1)
    assert float(s) == pytest.approx(expected, rel=1e-12)
    # a gap breaks the pair: minute 3 missing, 4 not paired with 2
    gapped = [*ks, _k(4, "100", "100", "100", "100")]
    s2 = sigma_1m(gapped)
    assert s2 is not None
    assert s2 == s


def _brute_rise(ks: list[MarkKline], window_min: int) -> D:
    best = D(0)
    for a in ks:
        for b in ks:
            if a.open_ms <= b.open_ms <= a.open_ms + window_min * 60_000:
                best = max(best, b.high / a.open - 1)
    return best


def test_max_rise_hand_computed() -> None:
    ks = [
        _k(0, "100", "100", "99", "100"),
        _k(1, "100", "103", "100", "102"),
        _k(5, "90", "91", "90", "90"),
    ]
    assert max_rise(ks, 2) == D("0.03")
    assert max_rise(ks, 10) == D("0.03")  # 91/90-1 = 0.0111 < 3 %
    assert max_rise([], 5) is None
    flat = [_k(0, "100", "100", "99", "99"), _k(1, "99", "99", "98", "98")]
    assert max_rise(flat, 5) == D(0)  # highs below opens clamp to 0 rise


@pytest.mark.parametrize("seed", range(5))
def test_max_rise_matches_brute_force_with_gaps(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - test data
    ks = []
    price = D(100)
    for minute in range(200):
        if rng.random() < 0.15:
            continue  # gap
        o = price
        c = o * D(str(1 + rng.uniform(-0.01, 0.01)))
        h = max(o, c) * D(str(1 + rng.uniform(0, 0.005)))
        low = min(o, c) * D(str(1 - rng.uniform(0, 0.005)))
        ks.append(MarkKline(minute * 60_000, o, h, low, c))
        price = c
    for window in (1, 7, 30, 120):
        assert max_rise(ks, window) == _brute_rise(ks, window)
