"""B15: venue restriction and fixed capital budget of a shadow portfolio."""

from decimal import Decimal as D

import pytest

from nexus.domain.spread import TransferQuote, TransferStatus
from nexus.simulation.portfolio import (
    PaperConfig,
    PaperPortfolio,
    Rebalance,
    RebalanceStatus,
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


def test_exhausted_coin_budget_skips_as_coin_budget_exhausted() -> None:
    p = PaperPortfolio(_set_config(coin_per_route=500), venues=frozenset({"a", "b"}))
    p.mark_price("AAA", D(10))
    p.mark_price("BBB", D(10))
    assert p.ensure_seeded("a", "b", "AAA", T0)
    p.mark_price("ABC", D(100))
    outcome = p.trade("BBB/USDT", "BBB", "a", "b", FILL, T0 + 1)  # AAA is not idle yet
    assert outcome.skip_reason is SkipReason.COIN_BUDGET_EXHAUSTED


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


# ---------------------------------------------------------------- coin slot release (R1)

HOUR = 3_600_000
DAYMS = 24 * HOUR


def _slot_portfolio(*, release_ms: int | None = DAYMS, cost: str = "0.5") -> PaperPortfolio:
    config = PaperConfig(
        usdt_per_exchange=D(500),
        coin_per_route_usd=D(250),
        rebalance_threshold_pct=D(20),
        rebalance_delay_ms=DELAY,
        coin_budget_per_venue_usd=D(500),
        coin_idle_release_ms=release_ms,
        conversion_cost_pct=D(cost),
    )
    p = PaperPortfolio(config, venues=frozenset({"a", "b"}))
    for coin in ("AAA", "BBB", "CCC"):
        p.mark_price(coin, D(10))
    assert p.ensure_seeded("a", "b", "AAA", T0)
    assert p.ensure_seeded("a", "b", "BBB", T0 + HOUR)  # budget 500 is now used up
    return p


def test_idle_slot_is_converted_back_to_usdt_and_reused() -> None:
    p = _slot_portfolio()
    capital_before = p.valuation().capital
    p.mark_price("AAA", D(12))  # the idle coin gained 20 %
    now = T0 + DAYMS + 1  # AAA idle > 24 h, BBB (seeded 1 h later) is not
    assert p.ensure_seeded("a", "b", "CCC", now)
    assert ("b", "AAA") not in p.seeds
    assert ("b", "AAA") not in p.balances
    assert ("b", "CCC") in p.seeds
    assert ("b", "BBB") in p.seeds
    # 25 AAA at 12 = 300 USD gross, 0.5 % conversion cost = 1.5
    assert p.balance("b", "USDT") == D(500) + D("298.5")
    assert p.rebalance_costs == D("1.5")
    [conversion] = p.drain_conversions()
    assert (conversion.asset, conversion.network) == ("AAA", "conversion")
    assert conversion.fee_usd == D("1.5")
    assert conversion.status is RebalanceStatus.COMPLETED
    assert p.drain_conversions() == []
    # capital is fixed; the price gain and the cost are P&L, not new capital
    assert p.valuation().capital == capital_before + D(250)  # only the new CCC slot is new
    v = p.valuation()
    assert v.total_pnl == D("50") - D("1.5")  # +20 % of the 250 slot, minus the cost
    assert v.mark_to_market == D("50")


def test_slot_is_kept_while_not_idle_and_the_skip_is_budget_exhausted() -> None:
    p = _slot_portfolio()
    p.mark_price("AAA", D(10))
    outcome = p.trade("CCC/USDT", "CCC", "a", "b", FILL, T0 + DAYMS - 1)
    assert outcome.skip_reason is SkipReason.COIN_BUDGET_EXHAUSTED
    assert ("b", "AAA") in p.seeds
    assert p.drain_conversions() == []


def test_trading_a_coin_keeps_its_slot_busy() -> None:
    p = _slot_portfolio()
    traded = p.trade("AAA/USDT", "AAA", "a", "b", FILL, T0 + DAYMS + 5)
    assert traded.executed
    # AAA was just used -> BBB (idle since T0+1h) is the one released
    assert p.ensure_seeded("a", "b", "CCC", T0 + DAYMS + HOUR + 6)
    assert ("b", "BBB") not in p.seeds
    assert ("b", "AAA") in p.seeds


def test_no_release_when_disabled_or_transfer_in_flight() -> None:
    off = _slot_portfolio(release_ms=None)
    assert off.ensure_seeded("a", "b", "CCC", T0 + 10 * DAYMS)
    assert ("b", "CCC") not in off.seeds
    assert ("b", "AAA") in off.seeds

    p = _slot_portfolio()
    p.in_flight.append(
        Rebalance(
            "AAA", "a", "b", D(5), D(0), D(0), "BEP20", T0, T0 + DAYMS, RebalanceStatus.IN_FLIGHT
        )
    )
    assert p.ensure_seeded("a", "b", "CCC", T0 + DAYMS + HOUR + 5)
    assert ("b", "AAA") in p.seeds  # in flight: not convertible
    assert ("b", "BBB") not in p.seeds  # the other idle slot is used instead


def test_release_needs_a_price_and_a_clock() -> None:
    p = _slot_portfolio()
    p.prices.pop("AAA")
    p.prices.pop("BBB")
    assert p.ensure_seeded("a", "b", "CCC", T0 + 5 * DAYMS)
    assert ("b", "CCC") not in p.seeds  # idle slots without a price are not converted
    q = _slot_portfolio()
    assert q.ensure_seeded("a", "b", "CCC")  # now_ms unknown (0): never release
    assert ("b", "CCC") not in q.seeds


def test_config_validation_of_release_settings() -> None:
    with pytest.raises(ValueError, match="coin_idle_release_ms"):
        PaperConfig(D(1), D(1), D(20), 0, coin_idle_release_ms=0)
    with pytest.raises(ValueError, match="conversion_cost_pct"):
        PaperConfig(D(1), D(1), D(20), 0, conversion_cost_pct=D(100))
