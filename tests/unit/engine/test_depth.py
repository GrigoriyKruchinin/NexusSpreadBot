from decimal import Decimal as D

import pytest

from nexus.domain.models import PriceLevel
from nexus.engine.depth import buy_base, floor_to_step, max_base_for_quote, sell_base

ASKS = (PriceLevel(D(100), D(5)), PriceLevel(D(101), D(10)))
BIDS = (PriceLevel(D(102), D(4)), PriceLevel(D("101.5"), D(10)))


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [
        ("9.9504", "0.01", "9.95"),
        ("9.9504", None, "9.9504"),
        ("9.9504", "0", "9.9504"),
        ("123", "5", "120"),
        ("0.004", "0.01", "0.00"),
    ],
)
def test_floor_to_step(value: str, step: str | None, expected: str) -> None:
    assert floor_to_step(D(value), D(step) if step else None) == D(expected)


def test_max_base_for_quote_walks_levels() -> None:
    # 500 quote fills level 1 (5 base); remaining 500 at 101.
    assert max_base_for_quote(ASKS, D(1000)) == D(5) + D(500) / D(101)


def test_max_base_for_quote_exact_level_boundary() -> None:
    assert max_base_for_quote(ASKS, D(500)) == D(5)


def test_max_base_for_quote_insufficient_depth() -> None:
    assert max_base_for_quote(ASKS, D(2000)) is None  # only 1510 quote visible


def test_buy_base_cost_and_vwap() -> None:
    fill = buy_base(ASKS, D("9.95"))
    assert fill is not None
    assert fill.quote_amount == D("999.95")  # 5*100 + 4.95*101
    assert fill.levels_used == 2
    assert fill.vwap == D("999.95") / D("9.95")


def test_sell_base_proceeds() -> None:
    fill = sell_base(BIDS, D("9.93"))
    assert fill is not None
    assert fill.quote_amount == D("1009.895")  # 4*102 + 5.93*101.5


def test_walk_insufficient_depth() -> None:
    assert sell_base(BIDS, D(20)) is None


def test_zero_amount_is_empty_fill() -> None:
    fill = buy_base(ASKS, D(0))
    assert fill is not None
    assert fill.quote_amount == D(0)


def test_floor_to_step_extreme_ratio_does_not_overflow() -> None:
    assert floor_to_step(D("1e12"), D("1e-18")) == D("1e12")
