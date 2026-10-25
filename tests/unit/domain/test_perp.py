"""Perp domain types: validation (spec HT1 S1)."""

from decimal import Decimal

import pytest

from nexus.adapters.perp.registry import PerpRegistry
from nexus.adapters.registry import AdapterOptions
from nexus.domain.errors import DataValidationError, UnknownExchangeError
from nexus.domain.perp import (
    FundingInfo,
    FundingPayment,
    LeverageTier,
    MarkKline,
    PerpMarket,
    PerpTicker,
)

D = Decimal


def _market(**kw: object) -> PerpMarket:
    base: dict[str, object] = {
        "exchange": "okx",
        "symbol": "ABC/USDT:USDT",
        "base": "ABC",
        "contract_size": D("10"),
        "amount_step": D("1"),
        "min_qty": D("1"),
    }
    return PerpMarket(**{**base, **kw})  # type: ignore[arg-type]


def test_market_ok_and_lot_base() -> None:
    market = _market(mmr=D("0.025"), taker_fee=D("0.0005"), max_leverage=D("50"))
    assert market.lot_base == D("10")
    assert market.active
    assert not market.delisting


@pytest.mark.parametrize(
    "kw",
    [
        {"contract_size": D("0")},
        {"contract_size": D("-1")},
        {"amount_step": D("0")},
        {"min_qty": D("-1")},
        {"max_leverage": D("0.5")},
        {"mmr": D("0.6")},
        {"mmr": D("-0.01")},
        {"taker_fee": D("0.02")},
        {"taker_fee": D("-0.0001")},
    ],
)
def test_market_rejects_implausible(kw: dict[str, object]) -> None:
    with pytest.raises(DataValidationError):
        _market(**kw)


def test_ticker_validation() -> None:
    PerpTicker("okx", "A", D("1"), D("1.1"), D("1.05"), 1)
    PerpTicker("okx", "A", None, None, None, 1)
    with pytest.raises(DataValidationError):
        PerpTicker("okx", "A", D("1.1"), D("1.1"), None, 1)
    with pytest.raises(DataValidationError):
        PerpTicker("okx", "A", D("0"), D("1"), None, 1)


def test_funding_keeps_sign_and_validates() -> None:
    info = FundingInfo("okx", "A", D("-0.0036"), 10, D("1"), D("5"), D("5.1"), 2)
    assert info.rate == D("-0.0036")
    with pytest.raises(DataValidationError):
        FundingInfo("okx", "A", D("0.5"), None, None, None, None, 2)
    with pytest.raises(DataValidationError):
        FundingInfo("okx", "A", D("0.0001"), None, D("0"), None, None, 2)
    with pytest.raises(DataValidationError):
        FundingInfo("okx", "A", D("0.0001"), None, None, D("-1"), None, 2)
    with pytest.raises(DataValidationError):
        FundingPayment("A", 1, D("-0.9"))
    assert FundingPayment("A", 1, D("-0.01")).rate == D("-0.01")


def test_kline_validation() -> None:
    MarkKline(0, D("1"), D("2"), D("0.5"), D("1.5"))
    with pytest.raises(DataValidationError):
        MarkKline(0, D("1"), D("0.9"), D("0.5"), D("0.8"))  # high < open
    with pytest.raises(DataValidationError):
        MarkKline(0, D("1"), D("2"), D("1.2"), D("1.5"))  # low > open
    with pytest.raises(DataValidationError):
        MarkKline(0, D("0"), D("2"), D("0.5"), D("1"))


def test_tier_validation() -> None:
    LeverageTier(D("0"), D("50000"), D("50"), D("0.004"))
    LeverageTier(D("50000"), None, D("20"), D("0.01"))
    with pytest.raises(DataValidationError):
        LeverageTier(D("10"), D("10"), D("5"), D("0.01"))
    with pytest.raises(DataValidationError):
        LeverageTier(D("0"), None, D("0"), D("0.01"))
    with pytest.raises(DataValidationError):
        LeverageTier(D("0"), None, D("5"), D("0.7"))


def test_registry_has_no_credentials_parameter() -> None:
    registry = PerpRegistry()

    @registry.register("x")  # type: ignore[arg-type]
    def _factory(options: AdapterOptions) -> object:
        return object()

    assert registry.names() == ("x",)
    assert registry.create("x", AdapterOptions()) is not None
    with pytest.raises(ValueError, match="already registered"):
        registry.register("x")(_factory)
    with pytest.raises(UnknownExchangeError):
        registry.create("nope", AdapterOptions())
