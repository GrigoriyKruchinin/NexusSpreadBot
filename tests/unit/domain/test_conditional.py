import pytest

from nexus.domain.conditional import conditional_legs, touches_conditional

COND = ("bybit", "gateio")


@pytest.mark.parametrize(
    ("buy", "sell", "conditional", "expected"),
    [
        ("bybit", "okx", COND, True),  # buy leg only
        ("okx", "gateio", COND, True),  # sell leg only
        ("bybit", "gateio", COND, True),  # both legs
        ("binance", "okx", COND, False),  # neither
        ("bybit", "gateio", (), False),  # empty list
    ],
)
def test_touches_conditional(
    buy: str, sell: str, conditional: tuple[str, ...], expected: bool
) -> None:
    assert touches_conditional(buy, sell, conditional) is expected


def test_conditional_legs_order_and_dedup() -> None:
    assert conditional_legs("bybit", "gateio", COND) == ("bybit", "gateio")
    assert conditional_legs("okx", "gateio", COND) == ("gateio",)
    assert conditional_legs("bybit", "bybit", COND) == ("bybit",)
    assert conditional_legs("okx", "binance", COND) == ()
