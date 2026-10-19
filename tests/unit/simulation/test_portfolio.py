"""Paper portfolio with hand-computed scenarios (prices: ABC = $100)."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.spread import SpreadBreakdown, TransferQuote, TransferStatus
from nexus.simulation.portfolio import (
    PaperConfig,
    PaperPortfolio,
    RebalanceNeed,
    RebalanceStatus,
    Seed,
    SkipReason,
    TradeOutcome,
)

T0 = 1_800_000_000_000
DELAY = 30 * 60_000
CONFIG = PaperConfig(
    usdt_per_exchange=D(1000),
    coin_per_route_usd=D(1000),
    rebalance_threshold_pct=D(20),
    rebalance_delay_ms=DELAY,
)
# Buy 5 ABC for $500 on A (0.1 % fee in base -> 4.995), sell 4.99 ABC (lot 0.01) on B.
FILL = SpreadBreakdown(
    best_ask_buy=D(100),
    best_bid_sell=D("102.1"),
    vwap_buy=D(100),
    vwap_sell=D(102),
    base_bought=D(5),
    base_received=D("4.995"),
    base_sold=D("4.99"),
    cost_quote=D(500),
    proceeds_quote=D("508.98"),
    gross_spread_pct=D("2.1"),
    net_profit_usd=D("8.98"),
    net_profit_pct=D("1.796"),
    fee_buy_usd=D("0.5"),
    fee_sell_usd=D("0.51"),
    transfer_fee_usd=D(0),
    slippage_usd=D(0),
)
TRC20 = TransferQuote(TransferStatus.VERIFIED, network="TRC20", fee_base=D(1))
ABC_NET = TransferQuote(TransferStatus.VERIFIED, network="BEP20", fee_base=D("0.01"))


def _portfolio() -> PaperPortfolio:
    portfolio = PaperPortfolio(CONFIG)
    portfolio.mark_price("ABC", D(100))
    return portfolio


def _trade(portfolio: PaperPortfolio) -> TradeOutcome:
    return portfolio.trade("ABC/USDT", "ABC", "a", "b", FILL, T0)


def test_trade_moves_balances_and_books_profit() -> None:
    p = _portfolio()
    outcome = p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0)
    assert outcome.executed
    assert outcome.net_usd == D("8.98")
    assert p.seeds[("b", "ABC")] == Seed(D(10), D(100))  # $1,000 of coin at the seed price
    assert (p.balance("a", "USDT"), p.balance("a", "ABC")) == (D(500), D("4.995"))
    assert (p.balance("b", "USDT"), p.balance("b", "ABC")) == (D("1508.98"), D("5.01"))
    assert p.realized == D("8.98")


def test_insufficient_balances_skip_without_changes() -> None:
    p = _portfolio()
    _trade(p)
    _trade(p)
    before = dict(p.balances)
    outcome = p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0)
    assert outcome.skip_reason is SkipReason.INSUFFICIENT_USDT  # $0 left on A
    assert outcome.net_usd == 0
    assert p.balances == before
    p.balances[("a", "USDT")] = D(1000)
    assert p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0).skip_reason is (
        SkipReason.INSUFFICIENT_COIN  # only 0.02 ABC left on B
    )


@pytest.mark.parametrize(
    ("fill", "reason"),
    [
        (None, SkipReason.BOOKS_UNAVAILABLE),
        (replace(FILL, net_profit_usd=D(0)), SkipReason.SPREAD_GONE),
    ],
)
def test_vanished_or_missing_books_skip(fill: SpreadBreakdown | None, reason: SkipReason) -> None:
    p = _portfolio()
    assert p.trade("ABC/USDT", "ABC", "a", "b", fill, T0).skip_reason is reason
    assert p.realized == 0


def test_unpriced_coin_cannot_be_seeded() -> None:
    p = PaperPortfolio(CONFIG)
    assert p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0).skip_reason is SkipReason.NO_PRICE


def test_threshold_rebalance_with_fee_lock_and_arrival() -> None:
    p = _portfolio()
    _trade(p)
    assert p.rebalance_needs(T0) == []  # $500 on A is above 20 % of $1,000
    _trade(p)
    needs = p.rebalance_needs(T0)
    assert needs == [
        RebalanceNeed("USDT", "b", "a", D(1000)),  # refill A from B's surplus
        RebalanceNeed("ABC", "a", "b", D("9.98")),  # refill B to 10 ABC from A's coins
    ]
    usdt = p.start_rebalance(needs[0], TRC20, T0)
    abc = p.start_rebalance(needs[1], ABC_NET, T0)
    assert (usdt.status, usdt.fee_usd, usdt.arrives_at_ms) == (
        RebalanceStatus.IN_FLIGHT,
        D(1),
        T0 + DELAY,
    )
    assert abc.fee_usd == D("1.00")
    assert p.balance("b", "USDT") == D("1017.96")
    assert p.balance("a", "ABC") == D("0.01")
    assert p.rebalance_costs == D("2.00")
    # Locked: the trade cannot use the money in flight.
    assert p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0 + 1).skip_reason is (
        SkipReason.REBALANCE_IN_FLIGHT
    )
    assert p.rebalance_needs(T0 + 1) == []  # no second transfer while one is in flight
    assert p.settle(T0 + DELAY - 1) == []
    done = p.settle(T0 + DELAY)
    assert [r.status for r in done] == [RebalanceStatus.COMPLETED] * 2
    assert p.balance("a", "USDT") == D(999)  # 1,000 minus the 1 USDT network fee
    assert p.balance("b", "ABC") == D("9.99")  # 0.02 + 9.98 - 0.01
    assert p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0 + DELAY).executed


def test_valuation_and_mark_to_market_after_price_move() -> None:
    p = _portfolio()
    _trade(p)
    _trade(p)
    needs = p.rebalance_needs(T0)
    p.start_rebalance(needs[0], TRC20, T0)
    p.start_rebalance(needs[1], ABC_NET, T0)
    flat = p.valuation()  # in-flight amounts count (net of fees)
    assert flat.capital == D(3000)
    assert flat.equity == D("3016.96")
    assert (flat.realized, flat.rebalance_costs) == (D("17.96"), D("2.00"))
    assert flat.mark_to_market == D("1.00")  # 0.01 ABC of lot dust kept on the books
    p.mark_price("ABC", D(90))
    moved = p.valuation()
    assert moved.total_pnl == D("-83.04")
    assert moved.mark_to_market == D("-99.00")
    assert moved.return_on_capital_pct == D("-2.768")


def test_no_verified_network_blocks_and_retries_later() -> None:
    p = PaperPortfolio(replace(CONFIG, blocked_retry_ms=2 * DELAY))
    p.mark_price("ABC", D(100))
    _trade(p)
    _trade(p)
    usdt_need, abc_need = p.rebalance_needs(T0)
    p.start_rebalance(usdt_need, TRC20, T0)
    blocked = p.start_rebalance(abc_need, TransferQuote(TransferStatus.UNKNOWN, note="no data"), T0)
    assert (blocked.status, blocked.note, blocked.fee_usd) == (
        RebalanceStatus.BLOCKED,
        "no data",
        D(0),
    )
    assert p.balance("a", "ABC") == D("9.99")  # nothing moved
    p.settle(T0 + DELAY)
    assert p.trade("ABC/USDT", "ABC", "a", "b", FILL, T0 + DELAY).skip_reason is (
        SkipReason.NO_REBALANCE_PATH
    )
    assert p.rebalance_needs(T0 + DELAY) == []  # blocked: retry after 30 min
    retry = p.rebalance_needs(T0 + 2 * DELAY)
    assert [n.asset for n in retry] == ["ABC"]
    p.start_rebalance(retry[0], ABC_NET, T0 + 2 * DELAY)
    assert ("b", "ABC") not in p.blocked


def test_fee_above_amount_is_blocked() -> None:
    p = _portfolio()
    need = RebalanceNeed("ABC", "a", "b", D("0.5"))
    expensive = TransferQuote(TransferStatus.VERIFIED, network="ERC20", fee_base=D(1))
    assert p.start_rebalance(need, expensive, T0).status is RebalanceStatus.BLOCKED


def test_restore_round_trip() -> None:
    p = _portfolio()
    _trade(p)
    _trade(p)
    needs = p.rebalance_needs(T0)
    in_flight = [p.start_rebalance(n, q, T0) for n, q in zip(needs, (TRC20, ABC_NET), strict=True)]
    holdings = [
        (exchange, asset, amount, p.seeds.get((exchange, asset)))
        for (exchange, asset), amount in p.balances.items()
    ]
    restored = PaperPortfolio.restore(
        CONFIG, holdings, in_flight, {"realized": p.realized, "rebalance_costs": p.rebalance_costs}
    )
    restored.mark_price("ABC", D(100))
    assert restored.valuation() == p.valuation()
    assert restored.balances == p.balances


@pytest.mark.parametrize(
    "kwargs",
    [
        {"usdt_per_exchange": D(0)},
        {"rebalance_threshold_pct": D(100)},
        {"rebalance_threshold_pct": D(0)},
        {"rebalance_delay_ms": -1},
    ],
)
def test_config_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"positive|within|negative"):
        replace(CONFIG, **kwargs)  # type: ignore[arg-type]


def test_trade_size_is_capped_by_inventory() -> None:
    p = _portfolio()  # seeds on first use: $1,000 USDT on A and B, 10 ABC on B at $100
    assert p.trade_size("a", "b", "ABC", D(100)) == (D(1000), None)
    assert p.trade_size("a", "b", "ABC", D(99)) == (D(990), None)  # 10 ABC x $99 ask
    p.balances[("a", "USDT")] = D(400)
    assert p.trade_size("a", "b", "ABC", D(100)) == (D(400), None)
    p.balances[("a", "USDT")] = D(99)  # below 10 % of the $1,000 target
    assert p.trade_size("a", "b", "ABC", D(100)) == (D(0), SkipReason.INSUFFICIENT_USDT)
    p.balances[("a", "USDT")] = D(1000)
    p.balances[("b", "ABC")] = D("0.5")
    assert p.trade_size("a", "b", "ABC", D(100)) == (D(0), SkipReason.INSUFFICIENT_COIN)
    assert PaperPortfolio(CONFIG).trade_size("a", "b", "ABC", D(100)) == (
        D(0),
        SkipReason.NO_PRICE,  # no price yet: the coin cannot be seeded
    )
