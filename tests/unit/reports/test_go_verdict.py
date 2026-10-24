"""GO verdict branches (ADR 0008) on deterministic fixtures."""

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.reports.go_math import (
    DAY_MS,
    CapHour,
    SetAnalysis,
    SetData,
    SkipRecord,
    analyze_set,
)
from nexus.reports.go_verdict import (
    DATA_QUALITY,
    GO,
    GO_HOLD,
    INSUFFICIENT,
    NO_GO_LEGAL,
    NOT_GO,
    NOT_GO_TAX,
    Flag,
    GateStatus,
    OpsInputs,
    confidence,
    decide,
    evaluate_rate,
    quality_flags,
)
from tests.go_fixture import make_set, ms

START = ms(2026, 10, 1)
LIQ = D("0.3")
GOOD_OPS = OpsInputs(timed_out_pct=D("0.5"), membership_missing=0, regimes=("calm", "wild"))


def routes(n: int, scale: str) -> list[tuple[str, str, str, str, D]]:
    return [(f"C{i}/USDT", f"C{i}", "binance", "kucoin", D("2.0") * D(scale)) for i in range(n)]


def scenario(
    scale: str = "0.7",
    days: int = 45,
    *,
    n_routes: int = 10,
    factor: Callable[[int], D] | None = None,
    route_list: list[tuple[str, str, str, str, D]] | None = None,
) -> SetData:
    return make_set(
        "s",
        ("binance", "kucoin"),
        START,
        route_list or routes(n_routes, scale),
        run_id=1,
        until_ms=START + days * DAY_MS,
        factor=factor or (lambda _d: D(1)),
    )


def analysis(data: SetData, days: int = 45) -> SetAnalysis:
    return analyze_set(data, START + days * DAY_MS, LIQ)


def test_all_gates_pass_but_legal_gates_open_is_go_hold() -> None:
    v = decide(analysis(scenario()), GateStatus(open_gates=("G1.2", "DNI")), GOOD_OPS)
    assert v.label == GO_HOLD
    assert "G1.2, DNI" in v.reasons[0]
    assert v.open_gates == ("G1.2", "DNI")
    assert v.at_35 is not None
    assert v.at_35.passed
    assert v.confidence == "high"


def test_all_gates_pass_and_cleared_is_go() -> None:
    v = decide(analysis(scenario()), GateStatus(), GOOD_OPS)
    assert v.label == GO
    assert v.at_35 is not None
    assert v.at_35.concentration_ok
    assert v.at_35.stability_ok


def test_passes_at_15_but_not_at_35_is_tax_sensitive_rework() -> None:
    v = decide(analysis(scenario("0.6")), GateStatus(), GOOD_OPS)
    assert v.label == NOT_GO_TAX
    assert v.at_15 is not None
    assert v.at_15.passed
    assert v.at_35 is not None
    assert not v.at_35.passed
    assert any("after 35 %" in r for r in v.reasons)


def test_fails_at_both_rates_is_plain_rework() -> None:
    v = decide(analysis(scenario("0.1")), GateStatus(), GOOD_OPS)
    assert v.label == NOT_GO
    assert v.at_35 is not None
    assert not v.at_35.money_ok
    assert v.at_15 is not None
    assert not v.at_15.passed


def test_too_short_holdout_is_insufficient_data_with_days_missing() -> None:
    v = decide(analysis(scenario(days=10), 10), GateStatus(), GOOD_OPS)
    assert v.label == INSUFFICIENT
    assert "11.0 more days" in v.reasons[0]
    assert v.at_35 is None
    assert v.at_15 is None
    assert "nothing to refute" in v.refute[0]
    assert evaluate_rate(analysis(scenario(days=10), 10), D("0.35")) is None


def test_a_lawyer_no_go_overrides_good_numbers() -> None:
    v = decide(analysis(scenario()), GateStatus(legal_no_go=True), GOOD_OPS)
    assert v.label == NO_GO_LEGAL
    assert v.at_35 is not None
    assert v.at_35.passed


def test_every_period_must_be_positive() -> None:
    # a loss stretch inside the third holdout period (days 38-44 of 45)
    def bad(d: int) -> D:
        return D(-3) if 38 <= d <= 44 else D(1)

    v = decide(analysis(scenario("1.0", factor=bad)), GateStatus(), GOOD_OPS)
    assert v.at_35 is not None
    assert not v.at_35.periods_positive
    assert v.label == NOT_GO
    assert any("not positive" in r for r in v.reasons)


def test_one_period_may_not_carry_more_than_60_percent_of_the_positive_net() -> None:
    def lumpy(d: int) -> D:
        return D(8) if 15 <= d < 22 else D("0.3")  # all of it in holdout period 1

    v = decide(analysis(scenario("1.0", factor=lumpy)), GateStatus(), GOOD_OPS)
    assert v.at_35 is not None
    assert not v.at_35.share_ok
    assert v.at_35.max_period_share > D("0.6")
    assert any("(> 60 %)" in r for r in v.reasons)


def test_at_least_half_of_the_periods_must_reach_the_bar() -> None:
    def weak(d: int) -> D:
        return D("0.1") if d >= 22 else D("2.5")  # period 1 strong, periods 2-4 positive but weak

    v = decide(analysis(scenario("1.0", factor=weak)), GateStatus(), GOOD_OPS)
    assert v.at_35 is not None
    assert v.at_35.periods_positive
    assert not v.at_35.periods_at_bar_ok
    assert v.at_35.periods_at_bar_needed == 2
    assert any("periods >=" in r for r in v.reasons)


def test_strict_concentration_fails_on_two_dominant_routes() -> None:
    star = [(f"S{i}/USDT", f"S{i}", "binance", "kucoin", D("30")) for i in range(2)]
    small = routes(8, "0.1")
    v = decide(analysis(scenario(route_list=star + small)), GateStatus(), GOOD_OPS)
    assert v.at_35 is not None
    assert v.at_35.money_ok
    assert not v.at_35.ex_routes_ok
    assert not v.at_35.ex_coins_ok
    assert v.label == NOT_GO
    assert any("ex-top-2 routes" in r for r in v.reasons)
    assert any("ex-top-2 coins" in r for r in v.reasons)
    assert v.refute[-1].startswith("top-2 routes: S0/USDT")


def test_ex_top_two_coins_can_fail_alone() -> None:
    # two coins with two routes each: removing the two routes of one coin does not hurt much,
    # but removing the two best COINS removes four routes
    legs = [("A/USDT", "A", "binance", "kucoin"), ("A/USDT", "A", "kucoin", "binance")]
    legs += [("B/USDT", "B", "binance", "kucoin"), ("B/USDT", "B", "kucoin", "binance")]
    rich = [(s, b, x, y, D("12")) for s, b, x, y in legs]
    v = decide(analysis(scenario(route_list=rich + routes(8, "0.2"))), GateStatus(), GOOD_OPS)
    assert v.at_35 is not None
    assert v.at_35.ex_routes_pct > v.at_35.ex_coins_pct  # coins group two routes each


def test_heartbeat_gaps_block_the_verdict() -> None:
    data = replace(scenario(), caps=())  # no sweep rows at all
    v = decide(analysis(data), GateStatus(), GOOD_OPS)
    assert v.label == DATA_QUALITY
    assert "without a sweep" in v.reasons[0]


def test_exhausted_coin_budget_blocks_the_verdict() -> None:
    skips = tuple(SkipRecord(START + i * 3_600_000, "coin_budget_exhausted") for i in range(400))
    v = decide(analysis(replace(scenario(), skips=skips)), GateStatus(), GOOD_OPS)
    assert v.label == DATA_QUALITY
    assert any("coin_budget_exhausted" in r for r in v.reasons)


def test_timed_out_candidates_block_the_verdict() -> None:
    ops = OpsInputs(timed_out_pct=D("3.5"), regimes=("a", "b"))
    v = decide(analysis(scenario()), GateStatus(), ops)
    assert v.label == DATA_QUALITY
    assert "3.5 %" in v.reasons[0]


def test_confidence_levels() -> None:
    a = analysis(scenario())
    assert confidence(quality_flags(a, GOOD_OPS)) == "high"
    assert confidence(quality_flags(a, OpsInputs(timed_out_pct=D(1), regimes=("x", "x")))) == "low"
    assert confidence(quality_flags(a, OpsInputs(regimes=("a", "b")))) == "medium"  # N2 unverified
    assert confidence([Flag("mtm_dominated", "x")]) == "medium"
    assert confidence([Flag("cap_bound", "x")]) == "medium"
    assert confidence([]) == "high"


def test_cap_bound_over_20_percent_lowers_confidence_without_blocking() -> None:
    caps = tuple(CapHour(c.hour_ms, c.sweeps, c.sweeps // 2, 5, 0) for c in scenario().caps)
    v = decide(analysis(replace(scenario(), caps=caps)), GateStatus(), GOOD_OPS)
    assert v.label == GO
    assert any(f.code == "cap_bound" for f in v.flags)
    assert v.confidence == "medium"


@pytest.mark.parametrize("label", ["tax", "plain"])
def test_refute_lines_always_name_the_numbers_that_break_the_verdict(label: str) -> None:
    v = decide(analysis(scenario("0.6" if label == "tax" else "0.1")), GateStatus(), GOOD_OPS)
    text = "\n".join(v.refute)
    assert "35 % tax line" in text
    assert "smallest period" in text
    assert "ex-top-2 routes" in text
