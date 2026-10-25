"""HT1 S8: pre-checks a-f with exact skip reasons, sizing, rounding, route choice."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.perp import FundingInfo, PerpTicker
from nexus.simulation import hedged
from nexus.simulation.basis import BasisBuffer
from nexus.simulation.hedged import (
    EntryDecision,
    SkipReason,
    evaluate_entry,
    funding_cost_fraction,
    funding_events,
    kline_coverage,
    liq_price,
)
from tests.unit.simulation.hedged_fixtures import (
    A_BOOK,
    B_BOOK,
    COIN,
    NOW,
    PERP,
    SPOT,
    book,
    config,
    hedge_inputs,
    klines,
    levels,
    net,
    perp_market,
    request,
    spot_market,
    state,
    transfer_info,
)


def _run(req=None, st=None, cfg=None) -> EntryDecision:  # type: ignore[no-untyped-def]
    return evaluate_entry(cfg or config(), req or request(), st or state())


def _hedges(**kw: object):  # type: ignore[no-untyped-def]
    return {"kucoin": hedge_inputs("kucoin", **kw)}


def test_clean_scenario_hand_computed_plan() -> None:
    d = _run()
    assert d.accepted
    p = d.plan
    assert p is not None
    assert p.hedge_venue == "kucoin"
    # q_buy = floor((10 + 0.01) / 0.999, 0.01) = 10.02 ; q = floor(10.02*0.999 - 0.01) = 9.99
    assert (p.q_buy, p.q, p.q_h) == (D("10.02"), D("9.99"), D("9.99"))
    assert p.cost == D("1002.000")  # 10.02 coins at 100.0
    assert (p.a_vwap, p.b0, p.f0) == (D("100.0"), D("101.5"), D("101.3"))
    assert p.margin == D("9.99") * D("101.3") / 2
    assert p.entry_fee == D("0.0006") * D("9.99") * D("101.3")
    assert p.p_liq == D("101.3") * (1 + D("0.5") - D("0.025"))
    assert p.s_usd == D("9.99") * D("101.5") * D("0.999") - D("1002.000")
    p_exp = 2 * D("0.0006") * D("9.99") * D("101.3") + D("9.99") * D("0.05")
    expected = p.s_usd - p_exp - p.leg_reserve - p.rb_reserve  # positive funding counts 0
    assert p.leg_reserve == D("0.0005") * p.cost
    assert p.rb_reserve == D(1) * p.cost / D(3000)
    assert float(p.e_net) == pytest.approx(float(expected), abs=1e-9)
    assert p.network == "TRC20"
    assert p.tau_p95_min >= p.tau_p50_min == D(5)  # 3 + 20*3 s/60 = 1 + 1 credit


# ------------------------------------------------------------------ (a)


def test_no_perp_and_identity_mismatch() -> None:
    assert _run(request(hedges=_hedges(market=None))).reason is SkipReason.NO_PERP
    other = perp_market("kucoin", base="XYZ")
    d = _run(request(hedges=_hedges(market=other)))
    assert d.reason is SkipReason.NO_PERP
    assert "base" in d.detail


def test_perp_inactive_and_delisting() -> None:
    inactive = _run(request(hedges=_hedges(market=perp_market("kucoin", active=False))))
    assert inactive.reason is SkipReason.PERP_INACTIVE
    delisting = _run(request(hedges=_hedges(market=perp_market("kucoin", delisting=True))))
    assert delisting.reason is SkipReason.PERP_INACTIVE


# ------------------------------------------------------------------ (b) in order


def test_perp_data_stale_variants() -> None:
    old_ticker = PerpTicker("kucoin", PERP, D("101.3"), D("101.35"), D("101.32"), NOW - 61_000)
    assert _run(request(hedges=_hedges(ticker=old_ticker))).reason is SkipReason.PERP_DATA_STALE
    fund = hedge_inputs("kucoin").funding
    assert fund is not None
    old_fund = replace(fund, received_at_ms=NOW - 16 * 60_000)
    assert _run(request(hedges=_hedges(funding=old_fund))).reason is SkipReason.PERP_DATA_STALE
    assert _run(request(hedges=_hedges(funding=None))).reason is SkipReason.PERP_DATA_STALE


def test_perp_thin() -> None:
    thin = book("kucoin", PERP, levels(("101.3", "0.5"), ("90", "100")), levels(("101.35", "100")))
    assert _run(request(hedges=_hedges(book=thin))).reason is SkipReason.PERP_THIN


def test_leverage_unknown_ok_and_known_low_skips() -> None:
    assert _run(request(hedges=_hedges(market=perp_market("kucoin", max_leverage=None)))).accepted
    low = perp_market("kucoin", max_leverage=D("1.5"))
    assert _run(request(hedges=_hedges(market=low))).reason is SkipReason.LEVERAGE


def test_funding_pessimistic_cost_over_tau_p95() -> None:
    fund = hedge_inputs("kucoin").funding
    assert fund is not None
    # one funding time inside the ~12 min window, rate -1 % x 1.5 stress = 1.5 % > 0.3 %
    bad = replace(fund, rate=D("-0.01"), next_funding_ms=NOW + 60_000)
    assert _run(request(hedges=_hedges(funding=bad))).reason is SkipReason.FUNDING
    # same rate but no funding time inside the window: allowed
    far = replace(fund, rate=D("-0.01"), next_funding_ms=NOW + 3_600_000)
    assert _run(request(hedges=_hedges(funding=far))).accepted


def test_history_missing_klines_or_tiers() -> None:
    few = klines(minutes=600)
    assert _run(request(hedges=_hedges(klines=few))).reason is SkipReason.PERP_HISTORY_MISSING
    no_tiers = _run(request(hedges=_hedges(tiers_ready=False)))
    assert no_tiers.reason is SkipReason.PERP_HISTORY_MISSING
    ok = klines(minutes=1300)  # 90.3 % coverage passes
    assert _run(request(hedges=_hedges(klines=ok))).accepted


def test_liq_risk_distance_vs_requirement() -> None:
    d = _run(cfg=config(leverage=D(4)))  # 1/4 - 0.025 = 0.225 < 0.30
    assert d.reason is SkipReason.LIQ_RISK
    # a violent history raises the requirement above the 0.475 distance
    wild = []
    for i, k in enumerate(klines()):
        price = D("100") if i % 2 else D("160")
        wild.append(replace(k, open=price, high=price, low=price, close=price))
    assert _run(request(hedges=_hedges(klines=wild))).reason is SkipReason.LIQ_RISK


def test_first_failing_check_wins() -> None:
    stale = PerpTicker("kucoin", PERP, D("101.3"), D("101.35"), D("101.32"), NOW - 120_000)
    thin = book("kucoin", PERP, levels(("101.3", "0.5")), levels(("101.35", "100")))
    d = _run(
        request(
            hedges=_hedges(ticker=stale, book=thin, market=perp_market("kucoin", max_leverage=D(1)))
        )
    )
    assert d.reason is SkipReason.PERP_DATA_STALE


# ------------------------------------------------------------------ (c) transfer


def test_transfer_blocked_variants() -> None:
    assert _run(request(src_info=None)).reason is SkipReason.TRANSFER_BLOCKED
    closed = transfer_info("kucoin", net("TRC20", deposit_enabled=False))
    assert _run(request(dst_info=closed)).reason is SkipReason.TRANSFER_BLOCKED
    busy = transfer_info("kucoin", net("TRC20", busy=True))
    assert _run(request(dst_info=busy)).reason is SkipReason.TRANSFER_BLOCKED
    nofee = transfer_info("okx", net("TRC20", withdraw_fee=None))
    assert _run(request(src_info=nofee)).reason is SkipReason.TRANSFER_BLOCKED


def test_min_withdraw_and_min_deposit_boundaries() -> None:
    # q_buy = 10.02 (sent from A), q = 9.99 (credited at B)
    assert _run(
        request(src_info=transfer_info("okx", net("TRC20", withdraw_min=D("10.02"))))
    ).accepted
    over = transfer_info("okx", net("TRC20", withdraw_min=D("10.03")))
    assert _run(request(src_info=over)).reason is SkipReason.BELOW_MIN_WITHDRAW
    assert _run(
        request(dst_info=transfer_info("kucoin", net("TRC20", deposit_min=D("9.99"))))
    ).accepted
    dep = transfer_info("kucoin", net("TRC20", deposit_min=D("10")))
    assert _run(request(dst_info=dep)).reason is SkipReason.BELOW_MIN_WITHDRAW


def test_metadata_stale() -> None:
    assert _run(request(src_loaded_ms=NOW - 46 * 60_000)).reason is SkipReason.METADATA_STALE
    assert _run(request(dst_loaded_ms=None)).reason is SkipReason.METADATA_STALE
    assert _run(request(dst_loaded_ms=NOW - 45 * 60_000)).accepted


def test_network_choice_minimises_fee_plus_funding() -> None:
    src = transfer_info(
        "okx", net("ERC20", withdraw_fee=D("0.2")), net("TRC20"), net("SOL", withdraw_fee=D("0.05"))
    )
    dst = transfer_info("kucoin", net("ERC20"), net("TRC20"), net("SOL"))
    p = _run(request(src_info=src, dst_info=dst)).plan
    assert p is not None
    assert p.network == "TRC20"  # fee 0.01
    src2 = transfer_info("okx", net("TRC20", busy=True), net("SOL", withdraw_fee=D("0.05")))
    dst2 = transfer_info("kucoin", net("TRC20"), net("SOL"))
    p2 = _run(request(src_info=src2, dst_info=dst2)).plan
    assert p2 is not None
    assert p2.network == "SOL"
    assert p2.withdraw_fee == D("0.05")


# ------------------------------------------------------------------ (d) sellable on B


def test_sell_thin_and_inactive_and_min_cost() -> None:
    req = request()
    thin = book("kucoin", SPOT, levels(("101.5", "0.4")), levels(("101.6", "10")))
    assert _run(replace(req, b=replace(req.b, book=thin))).reason is SkipReason.SELL_THIN
    inactive = replace(req.b, market=spot_market("kucoin", active=False))
    assert _run(replace(req, b=inactive)).reason is SkipReason.SELL_THIN
    costly = replace(req.b, market=spot_market("kucoin", min_cost=D(5000)))
    assert _run(replace(req, b=costly)).reason is SkipReason.SELL_THIN


# ------------------------------------------------------------------ sizing / UNFILLABLE


def test_unfillable_when_a_minimum_not_met_or_below_min_trade() -> None:
    req = request()
    big_min = replace(req.a, market=spot_market("okx", min_cost=D(5000)))
    assert _run(replace(req, a=big_min)).reason is SkipReason.UNFILLABLE
    free = {
        "src_info": transfer_info("okx", net("TRC20", withdraw_min=None)),
        "dst_info": transfer_info("kucoin", net("TRC20", deposit_min=None)),
    }
    assert (
        _run(request(**free), cfg=config(trade_notional_usd=D(90))).reason is SkipReason.UNFILLABLE
    )


def test_perp_contract_rounding_leaves_reported_dust() -> None:
    market = perp_market("kucoin", contract_size=D(10), amount_step=D(1), min_qty=D(1))
    d = _run(request(hedges=_hedges(market=market)), cfg=config(trade_notional_usd=D(2000)))
    p = d.plan
    assert p is not None
    assert p.q_h == D(10) * (p.q // D(10))  # whole contracts only
    assert p.q_h == D(10)
    assert p.q - p.q_h > 0  # dust is unhedged and reported by the position (line U)
    tiny = _run(request(hedges=_hedges(market=market)))  # 9.99 coins < one contract
    assert tiny.reason is SkipReason.UNFILLABLE


def test_perp_min_qty_enforced() -> None:
    market = perp_market("kucoin", min_qty=D(50))
    assert _run(request(hedges=_hedges(market=market))).reason is SkipReason.UNFILLABLE


def test_size_limited_by_depth_window_and_pools() -> None:
    req = request()
    shallow = book(
        "okx", SPOT, A_BOOK["bids"], levels(("100.0", "6"), ("100.1", "5"), ("101.0", "100"))
    )
    p = _run(replace(req, a=replace(req.a, book=shallow))).plan
    assert p is not None
    assert p.q_buy <= D(11)  # only 11 coins sit within +0.5 % of the best ask
    cut = _run(st=state(pools={"okx": D(600), "kucoin": D(3000)})).plan
    assert cut is not None
    assert cut.cost + cut.leg_reserve + cut.rb_reserve <= D(600)
    assert cut.cost >= D(100)
    hedge_cut = _run(st=state(pools={"okx": D(3000), "kucoin": D(300)})).plan
    assert hedge_cut is not None
    assert hedge_cut.margin + hedge_cut.entry_fee <= D(300)


# ------------------------------------------------------------------ (e) profit


def test_basis_warmup_variants() -> None:
    assert _run(request(hedges=_hedges(basis=None))).reason is SkipReason.BASIS_WARMUP
    short = BasisBuffer()
    for i in range(10):
        short.add(NOW - (10 - i) * 30_000, D("0.002"))
    assert _run(request(hedges=_hedges(basis=short))).reason is SkipReason.BASIS_WARMUP


def test_basis_outlier_uses_zscore() -> None:
    shifted = BasisBuffer()
    for i in range(130):
        shifted.add(
            NOW - (129 - i) * 30_000, D("0.0030") + (D("0.00002") if i % 2 else D("-0.00002"))
        )
    d = _run(request(hedges=_hedges(basis=shifted)))
    assert d.reason is SkipReason.BASIS_OUTLIER  # x_now 0.00197 vs median 0.0030: z about -10


def test_below_threshold_on_expected_net() -> None:
    assert _run(cfg=config(min_net_profit_usd=D(50))).reason is SkipReason.BELOW_THRESHOLD
    assert _run(cfg=config(min_net_profit_pct=D(2))).reason is SkipReason.BELOW_THRESHOLD


def test_pessimistic_net_includes_basis_sigma() -> None:
    noisy = BasisBuffer()
    x_now = (D("101.5") - D("101.3")) / D("101.325")
    for i in range(130):  # period-3 pattern: the 5 min lag (10 samples) pairs unequal phases
        noisy.add(NOW - (129 - i) * 30_000, x_now + (D("0.01"), D("-0.01"), D(0))[i % 3])
    d = _run(request(hedges=_hedges(basis=noisy)), cfg=config(basis_z_max=D(5)))
    assert d.reason is SkipReason.BELOW_THRESHOLD
    assert "P_net" in d.detail


def test_adverse_basis_reduces_expected_net_favourable_does_not_add() -> None:
    base = _run().plan
    assert base is not None
    x_now = (D("101.5") - D("101.3")) / D("101.325")

    def history(shift: D) -> BasisBuffer:
        buf = BasisBuffer()
        for i in range(130):
            buf.add(
                NOW - (129 - i) * 30_000, x_now + shift + (D("0.0001") if i % 2 else D("-0.0001"))
            )
        return buf

    # median above x_now: basis expected to widen back up -> favourable -> counted 0
    fav = _run(request(hedges=_hedges(basis=history(D("0.0002"))))).plan
    assert fav is not None
    assert fav.e_net == pytest.approx(base.e_net, abs=D("1e-6"))
    # median below x_now (x_now unusually high) -> adverse E_R < 0
    adv = _run(request(hedges=_hedges(basis=history(D("-0.0002"))))).plan
    assert adv is not None
    assert adv.e_net < base.e_net


# ------------------------------------------------------------------ (f) capital and limits


def test_insufficient_usdt_and_margin() -> None:
    assert (
        _run(st=state(pools={"okx": D(50), "kucoin": D(3000)})).reason
        is SkipReason.INSUFFICIENT_USDT
    )
    d = _run(st=state(pools={"okx": D(3000), "kucoin": D(10)}))
    assert d.reason is SkipReason.INSUFFICIENT_MARGIN


def test_shared_pool_when_hedge_on_buy_venue() -> None:
    req = request(hedges={"okx": hedge_inputs("okx")})
    p = _run(req, st=state(pools={"okx": D(2000), "kucoin": D(0)})).plan
    assert p is not None
    assert p.hedge_venue == "okx"
    assert p.cost + p.leg_reserve + p.rb_reserve + p.margin + p.entry_fee <= D(2000)


def test_limits_open_coin_cooldown() -> None:
    assert _run(st=state(open_count=4)).reason is SkipReason.MAX_POSITIONS
    assert _run(st=state(open_coins=frozenset({COIN}))).reason is SkipReason.COIN_OPEN
    recent = {(COIN, "okx", "kucoin"): NOW - 59_999}
    assert _run(st=state(last_fill_ms=recent)).reason is SkipReason.RECENT_FILL
    old = {(COIN, "okx", "kucoin"): NOW - 60_000}
    assert _run(st=state(last_fill_ms=old)).accepted
    assert _run(st=state(last_fill_ms={("OTHER", "okx", "kucoin"): NOW})).accepted


def test_stale_book_age_and_skew() -> None:
    req = request()
    old_a = book("okx", SPOT, A_BOOK["bids"], A_BOOK["asks"], age_ms=5001)
    assert _run(replace(req, a=replace(req.a, book=old_a))).reason is SkipReason.STALE_BOOK
    old_h = hedge_inputs(
        "kucoin",
        book=book(
            "kucoin",
            PERP,
            levels(("101.3", "20"), ("101.2", "50")),
            levels(("101.35", "100")),
            age_ms=5001,
        ),
    )
    assert _run(request(hedges={"kucoin": old_h})).reason is SkipReason.STALE_BOOK
    skewed_b = book("kucoin", SPOT, B_BOOK["bids"], B_BOOK["asks"], age_ms=4500)
    assert _run(replace(req, b=replace(req.b, book=skewed_b))).reason is SkipReason.STALE_BOOK
    edge = book("kucoin", SPOT, B_BOOK["bids"], B_BOOK["asks"], age_ms=4000)  # skew 3000 is allowed
    assert _run(replace(req, b=replace(req.b, book=edge))).accepted


def test_spread_gone_guard() -> None:
    plan = _run().plan
    assert plan is not None
    with pytest.raises(hedged._FailError) as exc:
        hedged._check_f(config(), request(), state(), replace(plan, s_usd=D(0)))
    assert exc.value.reason is SkipReason.SPREAD_GONE


# ------------------------------------------------------------------ candidates


def test_best_candidate_by_expected_net_then_order() -> None:
    cheaper = hedge_inputs("okx")
    assert cheaper.funding is not None
    pricey = replace(cheaper.funding, rate=D("-0.0005"), next_funding_ms=NOW + 60_000)
    req = request(
        hedges={"kucoin": hedge_inputs("kucoin"), "okx": replace(cheaper, funding=pricey)}
    )
    d = _run(req)
    assert d.hedge_venue == "kucoin"  # okx pays funding inside tau_p50
    tie = request(hedges={"okx": hedge_inputs("okx"), "kucoin": hedge_inputs("kucoin")})
    first = _run(tie)
    assert first.plan is not None
    assert first.hedge_venue == "okx"  # equal E_net (same fee config) -> request order wins


def test_skip_reports_most_advanced_failure_and_empty_candidates() -> None:
    req = request(
        hedges={
            "okx": hedge_inputs("okx", market=None),
            "kucoin": hedge_inputs("kucoin", market=perp_market("kucoin", max_leverage=D(1))),
        }
    )
    assert _run(req).reason is SkipReason.LEVERAGE
    assert _run(request(hedges={})).reason is SkipReason.NO_PERP


# ------------------------------------------------------------------ pure helpers


def test_funding_events_counts() -> None:
    h = 3_600_000
    assert funding_events(0, 8 * h, None, D(8)) == 1  # ceil(1)
    assert funding_events(0, 8 * h + 1, None, D(8)) == 2
    assert funding_events(0, 100, 50, D(8)) == 1
    assert funding_events(0, 100, 150, D(8)) == 0
    assert funding_events(0, 17 * h, 1 * h, D(8)) == 3  # at 1h, 9h, 17h
    assert funding_events(10 * h, 18 * h, 1 * h, D(8)) == 1  # rolls forward: 17h
    assert funding_events(5, 1, None, None) == 0


def test_funding_cost_fraction_signs() -> None:
    assert funding_cost_fraction(D("0.0001"), 3, D("1.5")) == 0  # income never banked
    assert funding_cost_fraction(D("-0.0002"), 2, D("1.5")) == D("0.0006")


def test_kline_coverage_and_liq_price() -> None:
    assert kline_coverage(klines(), NOW) == 1
    assert kline_coverage(klines(minutes=720), NOW) == D("0.5")
    assert kline_coverage([], NOW) == 0
    assert liq_price(D(100), D(2), D("0.025")) == D("147.5")


def test_config_perp_fee_resolution() -> None:
    cfg = config()
    assert cfg.perp_fee_for("kucoin") == D("0.0006")
    assert cfg.perp_fee_for("bybit", perp_market("bybit", taker_fee=D("0.0004"))) == D("0.0004")
    assert cfg.perp_fee_for("bybit") == D("0.0006")
    _ = FundingInfo  # keep import used for type docs
