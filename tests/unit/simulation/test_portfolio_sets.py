"""B15: venue restriction and fixed capital budget of a shadow portfolio."""

from decimal import Decimal as D

import pytest

from nexus.domain.spread import TransferQuote, TransferStatus
from nexus.simulation.portfolio import (
    PaperConfig,
    PaperPortfolio,
    SkipReason,
    allocate_capital,
)
from tests.unit.simulation.test_portfolio import CONFIG, DELAY, FILL, T0


def test_allocate_capital_splits_equally_and_sums_to_budget() -> None:
    usdt, coin = allocate_capital(D(10_000), 5, D(50))
    assert (usdt, coin) == (D(1000), D(1000))
    assert 5 * (usdt + coin) == D(10_000)
    usdt3, coin3 = allocate_capital(D(10_000), 3, D(60))
    assert usdt3 + coin3 == D(10_000) / 3
    assert usdt3 == D(10_000) / 3 * D("0.6")


def test_allocate_capital_validates() -> None:
    with pytest.raises(ValueError, match="venue"):
        allocate_capital(D(10_000), 1, D(50))
    with pytest.raises(ValueError, match="share"):
        allocate_capital(D(10_000), 3, D(100))


def _set_config(coin_per_route: int = 250, budget: int = 500) -> PaperConfig:
    return PaperConfig(
        usdt_per_exchange=D(500),
        coin_per_route_usd=D(coin_per_route),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=DELAY,
        coin_budget_per_venue_usd=D(budget),
    )


def test_coin_seeds_are_capped_by_the_venue_budget() -> None:
    p = PaperPortfolio(_set_config(), venues=frozenset({"a", "b"}))
    for coin, price in (("AAA", 10), ("BBB", 20), ("CCC", 5)):
        p.mark_price(coin, D(price))
        assert p.ensure_seeded("a", "b", coin)
    seeded = {asset: s.amount * s.price for (ex, asset), s in p.seeds.items() if ex == "b"}
    assert seeded == {"USDT": D(500), "AAA": D(250), "BBB": D(250)}  # CCC: budget used up
    assert ("b", "CCC") not in p.seeds
    assert p.balance("b", "CCC") == 0


def test_exhausted_coin_budget_skips_as_insufficient_coin() -> None:
    p = PaperPortfolio(_set_config(coin_per_route=500), venues=frozenset({"a", "b"}))
    p.mark_price("AAA", D(10))
    p.mark_price("BBB", D(10))
    assert p.ensure_seeded("a", "b", "AAA")
    p.mark_price("ABC", D(100))
    outcome = p.trade("BBB/USDT", "BBB", "a", "b", FILL, T0)
    assert outcome.skip_reason is SkipReason.INSUFFICIENT_COIN


def test_total_seeded_capital_never_exceeds_the_fixed_budget() -> None:
    usdt, coin = allocate_capital(D(10_000), 5, D(50))
    config = PaperConfig(
        usdt_per_exchange=usdt,
        coin_per_route_usd=D(250),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=DELAY,
        coin_budget_per_venue_usd=coin,
    )
    venues = ("a", "b", "c", "d", "e")
    p = PaperPortfolio(config, venues=frozenset(venues))
    for i in range(40):
        p.mark_price(f"C{i}", D(3) + i)
        p.ensure_seeded(venues[i % 5], venues[(i + 1) % 5], f"C{i}")
    assert p.valuation().capital <= D(10_000)


def test_venue_outside_the_set_is_refused() -> None:
    p = PaperPortfolio(CONFIG, venues=frozenset({"a", "b"}))
    p.mark_price("ABC", D(100))
    with pytest.raises(ValueError, match="'c'"):
        p.ensure_seeded("a", "c", "ABC")
    with pytest.raises(ValueError, match="'c'"):
        p.trade_size("c", "a", "ABC", D(100))


def test_rebalance_sources_never_leave_the_set() -> None:
    # Foreign balance that exists in the dict (e.g. restored from an old snapshot) must not be
    # picked as a refill source.
    p = PaperPortfolio(CONFIG, venues=frozenset({"a", "b"}))
    p.mark_price("ABC", D(100))
    p.ensure_seeded("a", "b", "ABC")
    p.balances[("c", "USDT")] = D(5_000)  # surplus outside the set
    p.balances[("a", "USDT")] = D(10)  # a is below the threshold
    needs = p.rebalance_needs(T0)
    assert all(n.from_exchange in {"a", "b"} and n.to_exchange in {"a", "b"} for n in needs)
    assert not any(n.from_exchange == "c" for n in needs)


def test_two_portfolios_are_independent() -> None:
    a = PaperPortfolio(CONFIG, venues=frozenset({"a", "b", "g"}))
    b = PaperPortfolio(CONFIG, venues=frozenset({"a", "b"}))
    for p in (a, b):
        p.mark_price("ABC", D(100))
    a.trade("ABC/USDT", "ABC", "a", "b", FILL, T0)
    assert b.balances == {}
    assert b.realized == 0
    blocked = TransferQuote(TransferStatus.UNKNOWN, note="no path")
    a.balances[("a", "USDT")] = D(10)
    need = a.rebalance_needs(T0)[0]
    a.start_rebalance(need, blocked, T0)
    assert a.blocked
    assert not b.blocked
    # B can still trade and sees no rebalance block from A
    assert b.trade("ABC/USDT", "ABC", "a", "b", FILL, T0).executed


def test_restore_keeps_the_venue_set() -> None:
    p = PaperPortfolio.restore(CONFIG, [], [], {}, venues=frozenset({"a", "b"}))
    assert p.venues == frozenset({"a", "b"})
