import math
from decimal import Decimal as D

import pytest

from nexus.simulation import transit
from nexus.simulation.transit import (
    estimate_transit,
    seed_for,
    tau_quantiles,
)


def test_block_time_table_and_aliases() -> None:
    assert transit.block_time_s("ETH") == D(12)  # alias of ERC20
    assert transit.block_time_s("bsc") == D(3)
    assert transit.block_time_s("ZIL") is None


def test_conf_median_hand_computed() -> None:
    # 12 confirmations * 12 s = 144 s = 2.4 min
    assert transit.conf_median_min("ERC20", 12, "okx") == D("2.4")
    # TRC20: 20 * 3 s = 1 min
    assert transit.conf_median_min("TRC20", 20, "kucoin") == D(1)


def test_unknown_confirmations_or_block_time_is_60_min() -> None:
    assert transit.conf_median_min("ERC20", None, "okx") == D(60)
    assert transit.conf_median_min("ERC20", 0, "okx") == D(60)
    assert transit.conf_median_min("ZIL", 10, "okx") == D(60)


def test_binance_destination_uses_larger_of_block_and_estimate() -> None:
    assert transit.conf_median_min("TRC20", 20, "binance", D(5)) == D(5)
    assert transit.conf_median_min("TRC20", 20, "binance", D("0.5")) == D(1)
    assert transit.conf_median_min("TRC20", 20, "okx", D(5)) == D(1)  # only binance uses it


def test_quantiles_closed_form() -> None:
    p50, p95 = tau_quantiles("kucoin", "okx", "TRC20", 20)
    assert p50 == D(5) + D(1) + D(1)
    expected = 5 * math.exp(0.7 * 1.6448536269514722) + 1.5 * 1 + 1
    assert float(p95) == pytest.approx(expected, rel=1e-12)
    for source in ("binance", "okx", "kucoin", "bybit", "gateio", "unknown_venue"):
        for conf in (None, 1, 100):
            a, b = tau_quantiles(source, "binance", "ERC20", conf)
            assert b >= a


def test_unknown_source_uses_slowest_median() -> None:
    assert transit.proc_median_min("gateio") == D(10)
    assert transit.proc_median_min("someone") == D(10)


def _est(key: str, **kw: object) -> transit.TransitEstimate:
    args: dict[str, object] = {
        "run_hash": "h",
        "position_key": key,
        "source_exchange": "okx",
        "dest_exchange": "kucoin",
        "network": "TRC20",
        "confirmations": 20,
    }
    args.update(kw)
    return estimate_transit(**args)  # type: ignore[arg-type]


def test_deterministic_for_a_seed_and_varies_with_key() -> None:
    assert _est("k1") == _est("k1")
    assert seed_for("h", "k1") != seed_for("h", "k2")
    assert seed_for("h", "k1") != seed_for("g", "k1")
    assert len({_est(f"k{i}").tau_min for i in range(20)}) > 1


def test_draw_never_below_floor_and_p95_above_p50() -> None:
    for i in range(200):
        est = _est(f"k{i}", p_stuck=0.0)
        assert est.tau_p95_min >= est.tau_p50_min
        assert est.tau_min > D(1) + D(1)  # conf (1) + credit (1) + positive processing
        assert not est.stuck


def test_stuck_tail_produces_stuck_hours() -> None:
    assert _est("any", p_stuck=1.0).tau_min == D(360)
    assert _est("any", p_stuck=1.0, stuck_h=3).stuck
    assert _est("any", p_stuck=1.0, stuck_h=3).tau_min == D(180)


def test_stuck_share_close_to_one_percent() -> None:
    stuck = sum(_est(f"k{i}").stuck for i in range(5000))
    assert 20 <= stuck <= 90  # 1 % of 5000 = 50, wide band for a seeded draw


def test_draw_median_near_p50() -> None:
    draws = sorted(_est(f"k{i}", p_stuck=0.0).tau_min for i in range(2000))
    p50 = _est("x", p_stuck=0.0).tau_p50_min
    assert abs(float(draws[1000]) - float(p50)) < 0.5
    assert float(draws[1900]) < float(_est("x").tau_p95_min) * 1.1
