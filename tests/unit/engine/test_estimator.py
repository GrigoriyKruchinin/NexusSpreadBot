"""Net spread estimator tests with hand-computed expected values."""

from dataclasses import replace
from decimal import Decimal as D
from typing import Any

import pytest

from nexus.domain.models import OrderBook
from nexus.domain.spread import EvaluationStatus, TransferQuote, TransferStatus
from nexus.engine.estimator import EstimatorConfig, NetSpreadEstimator
from tests.unit.engine.conftest import NOW, FixedClock, book, market

VERIFIED_FREE = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D(0))
UNKNOWN = TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata")


def _estimator(config: EstimatorConfig) -> NetSpreadEstimator:
    return NetSpreadEstimator(config, FixedClock())


def _simple_books(ask: str = "100", bid: str = "101") -> tuple[OrderBook, OrderBook]:
    return (
        book("a", asks=[(ask, "20")], bids=[(str(D(ask) - 1), "20")]),
        book("b", bids=[(bid, "20")], asks=[(str(D(bid) + 10), "20")]),
    )


def test_single_level_profitable(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    # 1000 USDT buys 10 ABC @100; fee 0.1% -> 9.99 ABC; sold @101 = 1008.99; fee 1.00899.
    assert ev.status is EvaluationStatus.PROFITABLE
    bd = ev.breakdown
    assert bd is not None
    assert bd.base_bought == D(10)
    assert bd.cost_quote == D(1000)
    assert bd.base_received == D("9.99")
    assert bd.base_sold == D("9.99")
    assert bd.fee_buy_usd == D(1)
    assert bd.fee_sell_usd == D("1.00899")
    assert bd.proceeds_quote == D("1007.98101")
    assert bd.net_profit_usd == D("7.98101")
    assert bd.net_profit_pct == D("0.798101")
    assert bd.gross_spread_pct == D(1)
    assert bd.slippage_usd == D(0)
    assert bd.transfer_fee_usd == D(0)
    assert ev.route_key == "ABC/USDT|a>b"
    assert not ev.fees_estimated
    assert ev.is_alertable
    assert ev.transfer_verified


def test_multi_level_with_lot_steps_and_transfer_fee(config: EstimatorConfig) -> None:
    buy = book("a", asks=[("100", "5"), ("101", "10")])
    sell = book("b", bids=[("102", "4"), ("101.5", "10")])
    transfer = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D("0.01"))
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a", step="0.01"),
        sell_market=market("b", step="0.01"),
        transfer=transfer,
    )
    bd = ev.breakdown
    assert bd is not None
    # Buy: 5 @100 + 4.950495.. @101 -> floor(9.9504..)=9.95 ; cost 500 + 4.95*101 = 999.95
    assert bd.base_bought == D("9.95")
    assert bd.cost_quote == D("999.95")
    # Fee 0.1% in base: 9.94005 ; minus 0.01 transfer -> 9.93005 -> floor 9.93
    assert bd.base_received == D("9.94005")
    assert bd.base_sold == D("9.93")
    # Sell: 4 @102 + 5.93 @101.5 = 1009.895 ; fee 1.009895 -> 1008.885105
    assert bd.fee_sell_usd == D("1.009895")
    assert bd.proceeds_quote == D("1008.885105")
    assert bd.net_profit_usd == D("8.935105")
    assert bd.net_profit_pct == D("8.935105") / D("999.95") * 100
    assert bd.gross_spread_pct == D(2)
    # Slippage: buy 999.95 - 9.95*100 = 4.95 ; sell 9.93*102 - 1009.895 = 2.965
    assert bd.slippage_usd == D("7.915")
    assert bd.transfer_fee_usd == D("0.01") * (D("1009.895") / D("9.93"))
    assert ev.status is EvaluationStatus.PROFITABLE


def test_usd_threshold_enforced_even_if_pct_passes(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(ask="100", bid="100.6")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    # 9.99 * 100.6 = 1004.994 ; fee 1.004994 -> net 3.989006 (0.3989 %) < $5
    bd = ev.breakdown
    assert bd is not None
    assert bd.net_profit_usd == D("3.989006")
    assert bd.net_profit_pct > D("0.3")
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD


def test_pct_threshold_enforced_even_if_usd_passes(config: EstimatorConfig) -> None:
    cfg = replace(config, min_net_profit_usd=D(1))
    buy, sell = _simple_books(ask="100", bid="100.4")
    ev = _estimator(cfg).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    # 9.99*100.4 = 1002.996 ; fee 1.002996 -> net 1.993004 (0.199 %) < 0.3 %
    assert ev.breakdown is not None
    assert ev.breakdown.net_profit_usd == D("1.993004")
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD


def test_fees_can_turn_gross_spread_into_loss(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(ask="100", bid="100.15")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.breakdown is not None
    assert ev.breakdown.net_profit_usd < 0
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD


@pytest.mark.parametrize(
    ("buy_ts", "sell_ts", "reason_part"),
    [
        (NOW - 6_000, NOW - 100, "age"),
        (NOW - 100, NOW - 6_000, "age"),
        (NOW - 4_000, NOW - 500, "skew"),
    ],
)
def test_stale_or_skewed_books_rejected(
    config: EstimatorConfig, buy_ts: int, sell_ts: int, reason_part: str
) -> None:
    buy = book("a", asks=[("100", "20")], ts=buy_ts)
    sell = book("b", bids=[("105", "20")], ts=sell_ts)
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.STALE_BOOK
    assert reason_part in ev.reason
    assert ev.breakdown is None


def test_no_spread(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(ask="100", bid="100")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.NO_SPREAD


def test_suspicious_spread_never_alerted(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(ask="100", bid="125")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.SUSPICIOUS_SPREAD
    assert ev.gross_spread_pct == D(25)
    assert not ev.is_alertable


def test_insufficient_buy_depth(config: EstimatorConfig) -> None:
    buy = book("a", asks=[("100", "5")])  # 500 USDT visible
    sell = book("b", bids=[("105", "20")])
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.INSUFFICIENT_DEPTH
    assert ev.reason == "buy side"


def test_insufficient_sell_depth(config: EstimatorConfig) -> None:
    buy = book("a", asks=[("100", "20")])
    sell = book("b", bids=[("105", "3")])
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.INSUFFICIENT_DEPTH
    assert ev.reason == "sell side"


def test_empty_side(config: EstimatorConfig) -> None:
    ev = _estimator(config).evaluate(
        buy_book=book("a"),
        sell_book=book("b", bids=[("105", "20")]),
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.INSUFFICIENT_DEPTH


def test_transfer_unavailable_rejected(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(bid="103")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=TransferQuote(TransferStatus.UNAVAILABLE, note="withdrawals disabled on a"),
    )
    assert ev.status is EvaluationStatus.TRANSFER_UNAVAILABLE
    assert ev.reason == "withdrawals disabled on a"


def test_unknown_transfer_allowed_without_fee_by_default(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=UNKNOWN,
    )
    assert ev.status is EvaluationStatus.PROFITABLE
    assert not ev.transfer_verified  # must be surfaced in the alert
    assert ev.breakdown is not None
    assert ev.breakdown.transfer_fee_usd == D(0)


def test_unknown_transfer_rejected_when_verification_required(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    ev = _estimator(replace(config, require_verified_transfer=True)).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=UNKNOWN,
    )
    assert ev.status is EvaluationStatus.TRANSFER_UNVERIFIED
    assert ev.meets_thresholds
    assert not ev.is_alertable
    assert ev.breakdown is not None  # fully priced for episodes / digest
    assert ev.breakdown.transfer_fee_usd == D(0)


def test_unverified_below_threshold_stays_below_threshold(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    strict = replace(config, require_verified_transfer=True, min_net_profit_usd=D(10_000))
    ev = _estimator(strict).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=UNKNOWN,
    )
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD
    assert not ev.meets_thresholds


def test_transfer_cost_can_be_excluded(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    expensive = TransferQuote(TransferStatus.VERIFIED, network="ERC20", fee_base=D(1))
    included = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=expensive,
    )
    excluded = _estimator(replace(config, include_transfer_cost=False)).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=expensive,
    )
    assert included.breakdown is not None
    assert excluded.breakdown is not None
    assert included.breakdown.base_sold == D("8.99")
    assert excluded.breakdown.base_sold == D("9.99")
    assert included.status is EvaluationStatus.BELOW_THRESHOLD  # 1 ABC ~ $101 fee


def test_transfer_fee_exceeding_amount(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=TransferQuote(TransferStatus.VERIFIED, network="X", fee_base=D(50)),
    )
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD
    assert "transfer fee" in ev.reason


@pytest.mark.parametrize(
    ("buy_kwargs", "sell_kwargs"),
    [
        ({"min_amount": "11"}, {}),
        ({"min_cost": "1001"}, {}),
        ({}, {"min_amount": "10"}),
        ({}, {"min_cost": "2000"}),
        ({"step": "100"}, {}),
    ],
)
def test_below_exchange_minimums(
    config: EstimatorConfig, buy_kwargs: dict[str, Any], sell_kwargs: dict[str, Any]
) -> None:
    buy, sell = _simple_books(bid="103")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a", **buy_kwargs),
        sell_market=market("b", **sell_kwargs),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.BELOW_MIN_ORDER


def test_inactive_market(config: EstimatorConfig) -> None:
    buy, sell = _simple_books(bid="103")
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a", active=False),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.status is EvaluationStatus.MARKET_INACTIVE


def test_same_exchange_rejected(config: EstimatorConfig) -> None:
    buy, _ = _simple_books()
    sell = book("a", bids=[("101", "20")])
    with pytest.raises(ValueError, match="different exchanges"):
        _estimator(config).evaluate(
            buy_book=buy,
            sell_book=sell,
            buy_market=market("a"),
            sell_market=market("a"),
            transfer=VERIFIED_FREE,
        )


def test_symbol_mismatch_rejected(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    with pytest.raises(ValueError, match="same symbol"):
        _estimator(config).evaluate(
            buy_book=buy,
            sell_book=sell,
            buy_market=market("a"),
            sell_market=market("b", symbol="XYZ/USDT"),
            transfer=VERIFIED_FREE,
        )


def test_config_from_settings() -> None:
    from nexus.config.groups import SpreadSettings

    cfg = EstimatorConfig.from_settings(SpreadSettings())
    assert cfg.min_net_profit_pct == D("0.3")
    assert cfg.reference_notional_usd == D(1000)


def test_book_market_mismatch_rejected(config: EstimatorConfig) -> None:
    buy, sell = _simple_books()
    with pytest.raises(ValueError, match="does not belong"):
        _estimator(config).evaluate(
            buy_book=buy,
            sell_book=sell,
            buy_market=market("b"),
            sell_market=market("a"),
            transfer=VERIFIED_FREE,
        )


def test_non_usd_quote_rejected(config: EstimatorConfig) -> None:
    buy = book("a", asks=[("100", "20")], symbol="ABC/TRY")
    sell = book("b", bids=[("101", "20")], symbol="ABC/TRY")
    with pytest.raises(ValueError, match="USD stablecoin"):
        _estimator(config).evaluate(
            buy_book=buy,
            sell_book=sell,
            buy_market=market("a", symbol="ABC/TRY"),
            sell_market=market("b", symbol="ABC/TRY"),
            transfer=VERIFIED_FREE,
        )


def test_estimated_fee_flag_propagates(config: EstimatorConfig) -> None:
    from dataclasses import replace as dc_replace

    buy, sell = _simple_books()
    ev = _estimator(config).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=dc_replace(market("a"), taker_fee_is_default=True),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.fees_estimated


def test_large_unverified_spread_is_suspicious(config: EstimatorConfig) -> None:
    cfg = replace(config, max_unverified_gross_spread_pct=D(5))
    buy, sell = _simple_books(ask="100", bid="106")

    def run(transfer: TransferQuote) -> EvaluationStatus:
        return (
            _estimator(cfg)
            .evaluate(
                buy_book=buy,
                sell_book=sell,
                buy_market=market("a"),
                sell_market=market("b"),
                transfer=transfer,
            )
            .status
        )

    assert run(UNKNOWN) is EvaluationStatus.SUSPICIOUS_SPREAD
    # Same network code but unknown contracts: token identity not proven (ticker collision).
    assert run(VERIFIED_FREE) is EvaluationStatus.SUSPICIOUS_SPREAD
    assert run(replace(VERIFIED_FREE, contract_verified=True)) is EvaluationStatus.PROFITABLE


def test_onchain_transfer_tax_is_charged(config: EstimatorConfig) -> None:
    # 10 ABC bought for $1,000 (0.1 % fee in base -> 9.99); a 1.5 % chain tax burns 0.14985,
    # 9.84015 arrive and are sold at 101 (993.85515) less 0.1 %: 992.86129485 -> -$7.13870515.
    buy, sell = _simple_books()
    taxed = replace(config, transfer_tax_pct={"ABC": D("1.5")})
    ev = _estimator(taxed).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert ev.breakdown is not None
    assert ev.breakdown.base_sold == D("9.84015")
    assert ev.breakdown.proceeds_quote == D("992.86129485")
    assert ev.breakdown.net_profit_usd == D("-7.13870515")
    assert ev.breakdown.transfer_fee_usd == D("0.14985") * D(101)
    assert ev.status is EvaluationStatus.BELOW_THRESHOLD  # the "persistent LUNC spread"


def test_tax_applies_on_top_of_the_withdrawal_fee_and_without_network_data(
    config: EstimatorConfig,
) -> None:
    buy, sell = _simple_books()
    taxed = replace(config, transfer_tax_pct={"ABC": D("1.5")})
    fee = TransferQuote(TransferStatus.VERIFIED, network="LUNC", fee_base=D(1))
    with_fee = _estimator(taxed).evaluate(
        buy_book=buy, sell_book=sell, buy_market=market("a"), sell_market=market("b"), transfer=fee
    )
    assert with_fee.breakdown is not None
    assert with_fee.breakdown.base_sold == D("8.85515")  # 9.99 - 1 - 8.99 x 1.5 %
    unknown = _estimator(taxed).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=TransferQuote(TransferStatus.UNKNOWN),
    )
    assert unknown.breakdown is not None
    assert unknown.breakdown.base_sold == D("9.84015")  # per-asset tax, network unknown
    untaxed = _estimator(replace(config, transfer_tax_pct={"XYZ": D(5)})).evaluate(
        buy_book=buy,
        sell_book=sell,
        buy_market=market("a"),
        sell_market=market("b"),
        transfer=VERIFIED_FREE,
    )
    assert untaxed.breakdown is not None
    assert untaxed.breakdown.base_sold == D("9.99")
