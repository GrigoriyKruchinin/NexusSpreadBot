"""Executable volume: largest net-positive volume on the visible books."""

from dataclasses import replace
from decimal import Decimal as D

from nexus.domain.spread import (
    EvaluationStatus,
    SpreadEvaluation,
    TransferQuote,
    TransferStatus,
)
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from tests.unit.engine.conftest import FixedClock, book, market

VERIFIED_FREE = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D(0))


def _evaluate(
    config: EstimatorConfig,
    *,
    asks: list[tuple[str, str]],
    bids: list[tuple[str, str]],
    fee: str = "0",
    step: str | None = None,
    transfer: TransferQuote = VERIFIED_FREE,
) -> SpreadEvaluation:
    return NetSpreadEstimator(config, FixedClock()).evaluate(
        buy_book=book("a", asks=asks, bids=[("99", "5")]),
        sell_book=book("b", bids=bids, asks=[("200", "5")]),
        buy_market=market("a", fee=fee, step=step),
        sell_market=market("b", fee=fee, step=step),
        transfer=transfer,
    )


def test_max_volume_stops_where_net_turns_non_positive(config: EstimatorConfig) -> None:
    # net(V) = V for V <= 10, then 20 - V: positive up to (excluding) 20; lot step 1 -> 19.
    ev = _evaluate(config, asks=[("100", "10"), ("102", "10")], bids=[("101", "20")], step="1")
    assert ev.status is EvaluationStatus.PROFITABLE
    volume = ev.volume
    assert volume is not None
    assert (volume.scanned_base, volume.scanned_quote) == (D(10), D(1000))
    assert volume.max_base == D(19)
    assert volume.max_quote == D(1000) + D(102) * 9
    assert volume.max_net_usd == D(1)


def test_whole_visible_depth_when_always_positive(config: EstimatorConfig) -> None:
    ev = _evaluate(config, asks=[("100", "20")], bids=[("101", "30")])
    assert ev.volume is not None
    assert (ev.volume.max_base, ev.volume.max_quote) == (D(20), D(2000))
    assert ev.volume.max_net_usd == D(20)


def test_max_volume_never_below_scanned(config: EstimatorConfig) -> None:
    ev = _evaluate(config, asks=[("100", "10")], bids=[("101", "30")])
    assert ev.volume is not None
    assert ev.volume.max_base == ev.volume.scanned_base == D(10)


def test_max_volume_respects_fees_and_bid_depth(config: EstimatorConfig) -> None:
    # Bids absorb only ~9.99 ABC after the buy fee, so 20 ABC cannot be sold: bisection.
    ev = _evaluate(config, asks=[("100", "20")], bids=[("101", "12")], fee="0.001", step="0.01")
    assert ev.volume is not None
    # sold = floor(0.999 V, 0.01) <= 12 -> V < 12.022, lot step 0.01 -> 12.02
    assert ev.volume.max_base == D("12.02")
    assert ev.volume.max_quote == D("1202")


def test_no_volume_for_non_profitable_evaluation(config: EstimatorConfig) -> None:
    ev = _evaluate(config, asks=[("100", "20")], bids=[("100.1", "30")])
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD
    assert ev.volume is None


def test_unverified_transfer_still_prices_volume_without_fee(config: EstimatorConfig) -> None:
    unknown = TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")
    ev = _evaluate(config, asks=[("100", "20")], bids=[("101", "30")], transfer=unknown)
    assert ev.status is EvaluationStatus.PROFITABLE
    assert ev.volume is not None


def test_unknown_transfer_blocks_alert_when_verification_required(
    config: EstimatorConfig,
) -> None:
    """R-03 stays: unknown transfer is priced but never PROFITABLE (no volume attached)."""
    strict = replace(config, require_verified_transfer=True)
    unknown = TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")
    ev = _evaluate(strict, asks=[("100", "20")], bids=[("101", "30")], transfer=unknown)
    assert ev.status is EvaluationStatus.TRANSFER_UNVERIFIED
    assert not ev.is_alertable
    assert ev.volume is None


def test_fixed_transfer_fee_shrinks_net(config: EstimatorConfig) -> None:
    fee = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D("0.05"))
    loose = replace(config, min_net_profit_usd=D(0), min_net_profit_pct=D(0))
    ev = _evaluate(loose, asks=[("100", "10"), ("102", "10")], bids=[("101", "20")], transfer=fee)
    assert ev.volume is not None
    # sold = V - 0.05; beyond 10 base: net(V) = 14.95 - V
    assert D(14) < ev.volume.max_base < D("14.95")


def test_transfer_tax_is_modelled(config: EstimatorConfig) -> None:
    taxed = replace(config, transfer_tax_pct={"ABC": D("0.1")})
    ev = _evaluate(taxed, asks=[("100", "10"), ("102", "10")], bids=[("101", "20")])
    assert ev.volume is not None
    # sold = 0.999 V; beyond 10 base: net(V) = 20 - 1.101 V -> V < 18.165
    assert D("18.1") < ev.volume.max_base < D("18.17")
