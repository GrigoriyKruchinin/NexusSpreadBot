"""HT1 S9: P&L identity, funding, liquidation, exits, capital, valuation."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.models import OrderBook
from nexus.domain.perp import MarkKline
from nexus.simulation.hedged import EntryRequest, HedgedConfig, evaluate_entry
from nexus.simulation.hedged_portfolio import (
    ExitStatus,
    HedgedPortfolio,
    HedgedPosition,
    HedgedStatus,
)
from tests.unit.simulation.hedged_fixtures import (
    COIN,
    NOW,
    PERP,
    SPOT,
    book,
    config,
    hedge_inputs,
    levels,
    perp_market,
    request,
)

VENUES = ["okx", "kucoin", "binance"]
EPS = D("1e-12")


def _open(
    cfg: HedgedConfig | None = None,
    req: EntryRequest | None = None,
    key: str = "k1",
) -> tuple[HedgedPortfolio, HedgedPosition]:
    cfg = cfg or config(p_stuck=0.0)
    req = req or request()
    port = HedgedPortfolio(cfg, VENUES, "run-hash")
    decision = evaluate_entry(cfg, req, port.entry_state())
    assert decision.plan is not None, decision.detail or decision.reason
    return port, port.open_position(decision.plan, req, key)


def _books(
    pos: HedgedPosition, now: int, delta_b: str = "0", delta_h: str = "0", depth: str = "1000"
) -> tuple[OrderBook, OrderBook]:
    """B bids and H asks at ``entry level + delta`` with ample depth."""
    db, dh = D(delta_b), D(delta_h)
    b = book(
        "kucoin",
        SPOT,
        levels((str(D("101.5") + db), depth)),
        levels((str(D("102") + db), depth)),
        age_ms=now - now + 500,
    )
    h = book(
        "kucoin",
        PERP,
        levels((str(D("101.2") + dh), depth)),
        levels((str(D("101.35") + dh), depth)),
        age_ms=500,
    )
    del pos
    return b, h


def _at(pos: HedgedPosition) -> int:
    return pos.arrive_ms + 2000


def _shift_books(now: int, delta_b: str, delta_h: str, depth: str = "1000"):  # type: ignore[no-untyped-def]
    db, dh = D(delta_b), D(delta_h)
    stamp = now - 500
    b = OrderBook(
        "kucoin",
        SPOT,
        levels((str(D("101.5") + db), depth)),
        levels((str(D("102") + db), depth)),
        stamp,
        stamp,
    )
    h = OrderBook(
        "kucoin",
        PERP,
        levels((str(D("101.2") + dh), depth)),
        levels((str(D("101.35") + dh), depth)),
        stamp,
        stamp,
    )
    return b, h


def _close(port, pos, delta_b: str, delta_h: str):  # type: ignore[no-untyped-def]
    now = _at(pos)
    b, h = _shift_books(now, delta_b, delta_h)
    return port.try_exit(pos, now, b, h), now


def _assert_identity(port: HedgedPortfolio, pos: HedgedPosition) -> None:
    assert pos.lines is not None
    lines = pos.lines
    delta_pools = sum(port.pools.values()) - port.config.capital_usd
    assert abs(lines.total - delta_pools) < EPS
    assert abs(pos.net_cash - delta_pools) < EPS
    total = (
        lines.s
        + lines.r
        + lines.d
        + lines.u
        + lines.p
        + lines.f
        - lines.leg_reserve
        - lines.rb
        - lines.liquidation
    )
    assert lines.total == total


# ------------------------------------------------------------------ entry bookkeeping


def test_open_position_moves_cash_and_locks_margin() -> None:
    port, pos = _open()
    plan = pos.plan
    assert (
        abs(port.pools["okx"] - (D(10000) / 3 - (plan.cost + plan.leg_reserve + plan.rb_reserve)))
        < EPS
    )
    assert abs(port.pools["kucoin"] - (D(10000) / 3 - (plan.margin + plan.entry_fee))) < EPS
    assert pos.status is HedgedStatus.IN_TRANSIT
    assert pos.arrive_ms == NOW + int(pos.tau_min * 60_000)
    assert port.last_fill_ms[(COIN, "okx", "kucoin")] == NOW
    state = port.entry_state()
    assert state.open_count == 1
    assert state.open_coins == {COIN}
    with pytest.raises(ValueError, match="duplicate"):
        port.open_position(plan, request(), "k1")
    assert abs(port.valuation({}, {}).ledger_residual) < EPS


def test_transit_draw_is_reproducible_per_key() -> None:
    _, a = _open(key="same")
    _, b = _open(key="same")
    _, c = _open(key="other")
    assert a.arrive_ms == b.arrive_ms
    assert a.arrive_ms != c.arrive_ms


def test_entry_beyond_pool_is_rejected_and_rolled_back() -> None:
    req = request()
    port = HedgedPortfolio(config(), VENUES, "h")
    plan = evaluate_entry(config(), req, port.entry_state()).plan
    assert plan is not None
    port.pools["kucoin"] = D(1)
    before = dict(port.pools)
    with pytest.raises(ValueError, match="pool"):
        port.open_position(plan, req, "k2")
    assert port.pools == before


def test_portfolio_needs_venues() -> None:
    with pytest.raises(ValueError, match="venue"):
        HedgedPortfolio(config(), [], "h")


# ----------------------------------------------- P&L identity: reference positions


def test_identity_price_up_uniform_shift() -> None:
    port, pos = _open()
    plan = pos.plan
    outcome, _ = _close(port, pos, "+10", "+10")
    assert outcome.status is ExitStatus.CLOSED
    assert pos.status is HedgedStatus.CLOSED
    lines = pos.lines
    assert lines is not None
    q, qh = plan.q, plan.q_h
    b1, f1 = D("111.5"), D("111.35")  # best levels shifted; one level, so VWAP == price
    assert lines.s == q * plan.b0 * (1 - plan.phi_b) - plan.cost
    assert lines.r == qh * ((b1 - f1) - (plan.b0 - plan.f0))
    assert lines.d == -q * plan.phi_b * (b1 - plan.b0)
    assert lines.u == (q - qh) * (b1 - plan.b0)
    assert lines.p == -plan.entry_fee - plan.phi_h * qh * f1
    assert lines.f == 0
    # exit perp is bought at the ask (101.35 + 10) vs entry sold at bid 101.3: basis moved by spread
    _assert_identity(port, pos)
    assert pos.q_open == 0
    assert pos.b1 == b1


def test_identity_price_down() -> None:
    port, pos = _open()
    _close(port, pos, "-20", "-20")
    lines = pos.lines
    assert lines is not None
    assert lines.d > 0  # fee drift: lower sale value, lower fee
    assert pos.b1 == D("81.5")
    _assert_identity(port, pos)


def test_identity_basis_change_lands_in_r() -> None:
    port, pos = _open()
    plan = pos.plan
    _close(port, pos, "+0.5", "0")
    lines = pos.lines
    assert lines is not None
    # b1 = 102.0, f1 = 101.35 (ask): (b1-f1) - (b0-f0) = 0.65 - 0.2
    assert lines.r == plan.q_h * (D("0.65") - D("0.2"))
    _assert_identity(port, pos)


def test_identity_with_dust_from_contract_rounding() -> None:
    market = perp_market("kucoin", contract_size=D(10), amount_step=D(1), min_qty=D(1))
    req = request(hedges={"kucoin": hedge_inputs("kucoin", market=market)})
    cfg = config(p_stuck=0.0, trade_notional_usd=D(2000))
    port, pos = _open(cfg, req)
    assert pos.plan.q_h == 10
    assert pos.plan.q > pos.plan.q_h
    _close(port, pos, "+3", "+3")
    lines = pos.lines
    assert lines is not None
    dust = pos.plan.q - pos.plan.q_h
    assert lines.u == dust * (D("104.5") - pos.plan.b0)
    assert lines.u != 0
    _assert_identity(port, pos)


# ------------------------------------------------------------------ funding


def test_funding_sign_idempotence_and_multiple_times() -> None:
    port, pos = _open()
    venue = pos.plan.hedge_venue
    before = port.pools[venue]
    t1, t2, t3 = NOW + 1000, NOW + 8 * 3_600_000, NOW + 16 * 3_600_000
    got = port.accrue_funding(pos, t1, D("0.0001"), D(100))
    assert got == pos.plan.q_h * 100 * D("0.0001")  # short receives when rate > 0
    assert port.accrue_funding(pos, t1, D("0.0001"), D(100)) is None  # idempotent
    neg = port.accrue_funding(pos, t2, D("-0.0003"), D(110))
    assert neg == -pos.plan.q_h * 110 * D("0.0003")
    port.accrue_funding(pos, t3, D("0.00005"), D(90))
    expected = pos.plan.q_h * (100 * D("0.0001") - 110 * D("0.0003") + 90 * D("0.00005"))
    assert pos.funding_total == expected
    assert port.pools[venue] == before + expected
    assert port.accrue_funding(pos, NOW - 1, D("0.0001"), D(100)) is None  # before entry
    assert port.accrue_funding(pos, NOW, D("0.0001"), D(100)) is None  # at entry: not held
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    port.try_exit(pos, now, b, h)
    assert pos.lines is not None
    assert pos.lines.f == expected
    _assert_identity(port, pos)
    assert port.accrue_funding(pos, now + 10, D("0.0001"), D(100)) is None  # perp closed


# ------------------------------------------------------------------ liquidation


def test_liquidation_loses_full_margin_and_spot_leg_continues() -> None:
    port, pos = _open()
    plan = pos.plan
    assert not port.check_liquidation(pos, plan.p_liq - D("0.01"), NOW + 1000)
    pools_h = port.pools["kucoin"]
    assert port.check_liquidation(pos, plan.p_liq, NOW + 5000)
    assert pos.status is HedgedStatus.LIQUIDATED
    assert pos.hedge_break
    assert pos.liquidated_ms == NOW + 5000
    assert port.pools["kucoin"] == pools_h  # margin is gone, nothing returns
    assert not port.check_liquidation(pos, plan.p_liq * 2, NOW + 6000)  # once only
    assert port.accrue_funding(pos, NOW + 7000, D("0.0001"), D(100)) is None  # no perp left
    now = _at(pos)
    b, _h = _shift_books(now, "+50", "+50")
    out = port.try_exit(pos, now, b, None)  # perp book not needed any more
    assert out.status is ExitStatus.CLOSED
    assert pos.status.value == "CLOSED_UNHEDGED"
    lines = pos.lines
    assert lines is not None
    assert lines.liquidation == plan.margin - plan.q_h * (plan.p_liq - plan.f0)
    assert lines.p == -plan.entry_fee  # no exit fee: the exchange closed the position
    assert pos.f1 == plan.p_liq
    _assert_identity(port, pos)
    # perp leg total = -margin - entry fee exactly
    perp_total = plan.q_h * (plan.f0 - plan.p_liq) - lines.liquidation + lines.p
    assert perp_total == -plan.margin - plan.entry_fee


def test_liquidation_by_kline_high_and_gap() -> None:
    port, pos = _open()
    p_liq = pos.plan.p_liq
    calm = [MarkKline(NOW + i * 60_000, D(100), D(120), D(99), D(100)) for i in range(5)]
    assert not port.check_liquidation_klines(pos, calm)
    spike = [*calm, MarkKline(NOW + 5 * 60_000, D(110), p_liq, D(109), D(111))]
    assert port.check_liquidation_klines(pos, spike)
    assert pos.liquidated_ms == NOW + 5 * 60_000
    assert not port.check_liquidation_klines(pos, spike)  # already liquidated
    port2, pos2 = _open()
    old = [MarkKline(NOW - 600_000, D(100), p_liq * 2, D(99), D(100))]
    assert not port2.check_liquidation_klines(pos2, old)  # before the entry
    assert not port2.check_liquidation_klines(pos2, spike[:1], since_ms=NOW + 10**9)


# ------------------------------------------------------------------ exits


def test_exit_waits_for_arrival_plus_latency() -> None:
    port, pos = _open()
    b, h = _shift_books(pos.arrive_ms, "0", "0")
    assert port.try_exit(pos, pos.arrive_ms + 1999, b, h).status is ExitStatus.NOT_ARRIVED
    assert pos.status is HedgedStatus.IN_TRANSIT
    out = port.try_exit(pos, pos.arrive_ms + 2000, *_shift_books(pos.arrive_ms + 2000, "0", "0"))
    assert out.status is ExitStatus.CLOSED
    assert port.try_exit(pos, pos.arrive_ms + 5000, b, h).status is ExitStatus.TERMINAL


def test_stale_b_book_retries_and_deposit_closed_waits() -> None:
    port, pos = _open()
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    old_b = replace(b, timestamp_ms=now - 6000, received_at_ms=now - 6000)
    assert port.try_exit(pos, now, old_b, h).status is ExitStatus.STALE
    assert pos.status is HedgedStatus.ARRIVED
    assert port.try_exit(pos, now, None, h).status is ExitStatus.STALE
    skewed_h = replace(h, timestamp_ms=now - 4000, received_at_ms=now - 4000)
    assert port.try_exit(pos, now, b, skewed_h).status is ExitStatus.HEDGE_UNPRICED
    assert port.try_exit(pos, now, b, h, deposit_open=False).status is ExitStatus.DEPOSIT_CLOSED
    assert pos.q_open == pos.plan.q


def test_unpriceable_hedge_keeps_both_legs_open_then_final_booking() -> None:
    port, pos = _open()
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    cash = dict(port.pools)
    out = port.try_exit(pos, now, b, None)
    assert out.status is ExitStatus.HEDGE_UNPRICED
    assert pos.hedge_unpriced
    assert pos.unpriced_since_ms == now
    assert port.pools == cash  # spot NOT sold while the hedge cannot be closed
    assert pos.q_open == pos.plan.q
    thin_h = replace(h, asks=levels(("101.35", "0.5")))
    assert port.try_exit(pos, now + 1, b, thin_h).status is ExitStatus.HEDGE_UNPRICED
    assert pos.unpriced_since_ms == now  # first time kept
    assert not port.final_booking_due(pos, pos.opened_ms + 29 * 3_600_000)
    final_at = pos.opened_ms + 30 * 3_600_000
    assert port.final_booking_due(pos, final_at)
    port.note_prices(pos, perp_price=D("103"), b_bid=D("101.0"))
    assert port.book_unpriced_final(pos, final_at, None)
    assert pos.status is HedgedStatus.CLOSED
    assert pos.hedge_unpriced_final
    lines = pos.lines
    assert lines is not None
    window = D("0.01")
    f1 = D("103") * (1 + window)
    assert pos.f1 == f1
    assert pos.b1 == D("101.0") * (1 - window)
    assert lines.p == -pos.plan.entry_fee - pos.plan.phi_h * pos.plan.q_h * f1
    _assert_identity(port, pos)
    assert not port.book_unpriced_final(pos, final_at, None)  # already closed


def test_final_booking_uses_fresh_b_book_when_available() -> None:
    port, pos = _open()
    final_at = pos.opened_ms + 31 * 3_600_000
    b = OrderBook(
        "kucoin", SPOT, levels(("100.0", "1000")), levels(("100.5", "1000")), final_at, final_at
    )
    assert port.book_unpriced_final(pos, final_at, b)
    assert pos.b1 == D("100.0")
    _assert_identity(port, pos)


def test_liquidation_takes_precedence_over_unpriced_final() -> None:
    port, pos = _open()
    assert port.check_liquidation(pos, pos.plan.p_liq, NOW + 1)
    assert not port.book_unpriced_final(pos, pos.opened_ms + 31 * 3_600_000, None)
    assert pos.status is HedgedStatus.LIQUIDATED


def test_partial_exit_then_remainder() -> None:
    port, pos = _open()
    plan = pos.plan
    now = _at(pos)
    # only 4 coins within the 1 % window on B; perp deep
    b, h = _shift_books(now, "0", "0", depth="1000")
    thin_b = replace(b, bids=levels(("101.5", "4"), ("90", "1000")))
    out = port.try_exit(pos, now, thin_b, h)
    assert out.status is ExitStatus.PARTIAL
    assert pos.status is HedgedStatus.ARRIVED
    assert pos.q_open == plan.q - 4
    assert pos.q_h_open == plan.q_h - D("4.00")  # floor(4 * qh/q, 0.01 lot) = 4.00
    assert pos.lines is None
    port.accrue_funding(pos, now + 1000, D("0.0001"), D(100))
    assert pos.funding_total == pos.q_h_open * 100 * D("0.0001")
    out2 = port.try_exit(pos, now + 2000, *_shift_books(now + 2000, "0", "0"))
    assert out2.status is ExitStatus.CLOSED
    assert pos.q_open == 0
    assert pos.q_h_open == 0
    assert pos.margin_open == 0
    _assert_identity(port, pos)


def test_thin_book_blocks_non_forced_exit() -> None:
    port, pos = _open()
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    no_depth = replace(b, bids=levels(("101.5", "1000")))
    # best bid exists but nothing within the window would need amount 0: emulate by empty bids
    empty = OrderBook("kucoin", SPOT, (), b.asks, b.timestamp_ms, b.received_at_ms)
    assert port.try_exit(pos, now, empty, h).status is ExitStatus.STALE
    assert port.try_exit(pos, now, no_depth, h).status is ExitStatus.CLOSED


def test_forced_exit_walks_the_book_and_prices_shortfall_adversely() -> None:
    port, pos = _open()
    plan = pos.plan
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    shallow_b = replace(b, bids=levels(("101.5", "4")))  # only 4 of ~10 coins exist
    shallow_h = replace(h, asks=levels(("101.35", "3")))
    out = port.try_exit(pos, now, shallow_b, shallow_h, forced=True)
    assert out.status is ExitStatus.CLOSED
    assert pos.status is HedgedStatus.FORCED_EXIT
    window = D("0.01")
    expected_gross = 4 * D("101.5") + (plan.q - 4) * D("101.5") * (1 - window)
    assert pos.sold_gross == expected_gross
    expected_perp = 3 * D("101.35") + (plan.q_h - 3) * D("101.35") * (1 + window)
    assert pos.perp_close_value == expected_perp
    _assert_identity(port, pos)


def test_forced_exit_with_deposit_closed_is_flagged() -> None:
    port, pos = _open()
    now = _at(pos)
    b, h = _shift_books(now, "0", "0")
    assert port.hold_exceeded(pos, pos.opened_ms + 24 * 3_600_000)
    assert not port.hold_exceeded(pos, pos.opened_ms + 24 * 3_600_000 - 1)
    out = port.try_exit(pos, now, b, h, deposit_open=False, forced=True)
    assert out.status is ExitStatus.CLOSED
    assert pos.deposit_closed_forced
    assert pos.status is HedgedStatus.FORCED_EXIT


# ------------------------------------------------------------------ rebalancing


def test_rebalance_refills_low_pool_from_largest_surplus() -> None:
    port = HedgedPortfolio(config(), VENUES, "h")
    port.pools["kucoin"] = D(1000)
    port.pools["binance"] = D("3800")
    port.pools["okx"] = D("2000")
    calls: list[tuple[str, str]] = []

    def route(src: str, dst: str) -> tuple[D, D] | None:
        calls.append((src, dst))
        return D("1.5"), D(10)

    started = port.plan_rebalances(NOW, route)
    target = port.pool_target
    low = [r for r in started if r.target == "kucoin"]
    assert len(low) == 1
    move = low[0]
    assert move.source == "binance"
    assert move.amount == min(target - D(1000), D("3800") - target)
    assert move.arrive_ms == NOW + 10 * 60_000
    assert port.pools["binance"] == D("3800") - move.amount
    assert port.plan_rebalances(NOW + 1, route) == []  # one in flight per target
    before = port.pools["kucoin"]
    assert port.settle_rebalances(NOW + 5 * 60_000) == []
    arrived = port.settle_rebalances(NOW + 10 * 60_000)
    assert [r.target for r in arrived] == ["kucoin"]
    assert port.pools["kucoin"] == before + move.amount
    assert port.rebalance_fee_paid == D("1.5")


def test_rebalance_blocked_route_retries_after_30_minutes() -> None:
    port = HedgedPortfolio(config(), VENUES, "h")
    port.pools["kucoin"] = D(500)
    port.pools["binance"] = port.pool_target + D(2000)
    assert port.plan_rebalances(NOW, lambda a, b: None) == []
    assert port.rebalance_retry_ms["kucoin"] == NOW + 30 * 60_000
    ok = lambda a, b: (D(1), D(5))  # noqa: E731
    assert port.plan_rebalances(NOW + 29 * 60_000, ok) == []
    assert len(port.plan_rebalances(NOW + 30 * 60_000, ok)) == 1


def test_rebalance_needs_a_donor_with_surplus() -> None:
    port = HedgedPortfolio(config(), VENUES, "h")
    for v in VENUES:
        port.pools[v] = D(1000)  # everybody is below the target and the threshold
    assert port.plan_rebalances(NOW, lambda a, b: (D(1), D(5))) == []
    solo = HedgedPortfolio(config(), ["okx"], "h")
    solo.pools["okx"] = D(1)
    assert solo.plan_rebalances(NOW, lambda a, b: (D(1), D(5))) == []


# ------------------------------------------------------------------ valuation (AC3)


@pytest.mark.parametrize("shift", ["-40", "-5", "0", "7", "63.5"])
def test_directional_mtm_zero_under_uniform_shift_dust_free(shift: str) -> None:
    port, pos = _open()
    assert pos.plan.q == pos.plan.q_h
    d = D(shift)
    mid = D("101.25") + d
    mark = D("101.32") + d
    val = port.valuation({COIN: mid}, {(COIN, "kucoin"): mark})
    assert abs(val.directional_mtm) < D("1e-9")
    assert abs(val.ledger_residual) < EPS
    # open basis MTM is shift invariant
    base = port.valuation({COIN: D("101.25")}, {(COIN, "kucoin"): D("101.32")})
    assert abs(val.open_basis_mtm - base.open_basis_mtm) < D("1e-9")


def test_directional_mtm_is_dust_only() -> None:
    market = perp_market("kucoin", contract_size=D(10), amount_step=D(1), min_qty=D(1))
    req = request(hedges={"kucoin": hedge_inputs("kucoin", market=market)})
    port, pos = _open(config(p_stuck=0.0, trade_notional_usd=D(2000)), req)
    dust = pos.plan.q - pos.plan.q_h
    mid, mark = D("110"), D("109")
    val = port.valuation({COIN: mid}, {(COIN, "kucoin"): mark})
    assert abs(val.directional_mtm - dust * (mid - pos.plan.b0)) < D("1e-9")


def test_liquidated_position_is_directional() -> None:
    port, pos = _open()
    port.check_liquidation(pos, pos.plan.p_liq, NOW + 1)
    mid = pos.plan.b0 + 5
    val = port.valuation({COIN: mid}, {})
    assert abs(val.directional_mtm - pos.q_open * 5) < D("1e-9")


def test_valuation_without_prices_uses_entry_references() -> None:
    port, pos = _open()
    val = port.valuation({}, {})
    assert val.open_basis_mtm == 0
    assert abs(val.directional_mtm) < D("1e-9")
    assert val.in_flight == 0
    assert val.equity == val.pools + val.open_value
    del pos


def test_equity_after_close_equals_capital_plus_total() -> None:
    port, pos = _open()
    _close(port, pos, "+10", "+10")
    val = port.valuation({}, {})
    assert pos.lines is not None
    assert abs(val.equity - port.config.capital_usd - pos.lines.total) < EPS
    assert val.open_value == 0
