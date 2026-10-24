"""GO report math: formulas, windows, concentration (hand-computed expectations)."""

from dataclasses import replace
from decimal import Decimal as D

from nexus.reports.go_math import (
    DAY_MS,
    HOUR_MS,
    CapHour,
    HoldingPoint,
    RebalanceRecord,
    RunInfo,
    SetData,
    SkipRecord,
    SnapshotSet,
    TradeRecord,
    after_tax,
    analyze_set,
    coin_mtm,
    common_window,
    concentration,
    daily_times,
    max_drawdown_pct,
    pct_per_month,
    per_month,
    snapshot_at,
    split_window,
    valuation_at,
    window_days,
    window_stats,
)
from tests.go_fixture import ms

S = ms(2026, 11, 1)  # a UTC midnight
LIQ = D("0.3")


def run(started: int = S, capital: str = "1000") -> RunInfo:
    return RunInfo(1, started, ("binance", "kucoin"), D(capital), "hash")


def usdt(venue: str, amount: str, seeded: str) -> HoldingPoint:
    return HoldingPoint(venue, "USDT", D(amount), D(1), D(seeded))


def abc(venue: str, amount: str, price: str, seed_price: str) -> HoldingPoint:
    seeded = D(amount) * D(seed_price)
    return HoldingPoint(venue, "ABC", D(amount), D(price), seeded)


def trade(at: int, net: str, symbol: str = "ABC/USDT", buy: str = "binance",
          sell: str = "kucoin", notional: str = "100") -> TradeRecord:  # fmt: skip
    return TradeRecord(at, symbol, symbol.split("/")[0], buy, sell, D(net), D(notional))


def rebal(
    at: int,
    fee_usd: str,
    *,
    asset: str = "USDT",
    to: str = "binance",
    src: str = "kucoin",
    network: str | None = "TRC20",
    status: str = "completed",
    arrives: int | None = None,
    amount: str = "100",
    fee: str = "1",
) -> RebalanceRecord:
    end = arrives if arrives is not None else at + HOUR_MS
    return RebalanceRecord(at, end, asset, src, to, D(amount), D(fee), D(fee_usd), network, status)


def tiny() -> SetData:
    """capital 1000; seeded 500 + 150 -> 350 unseeded cash; equity 1150 after 1 h."""
    snap = SnapshotSet(
        S + HOUR_MS,
        (usdt("binance", "600", "500"), abc("kucoin", "100", "2", "1.5")),
    )
    return SetData(
        "t",
        run(),
        snapshots=(snap,),
        trades=(trade(S + 2 * HOUR_MS, "30"), trade(S + 3 * HOUR_MS, "20")),
        skips=(SkipRecord(S + HOUR_MS, "spread_gone"), SkipRecord(S + DAY_MS + 1, "spread_gone")),
        rebalances=(
            rebal(S + HOUR_MS, "4", arrives=S + HOUR_MS),
            rebal(S + 2 * HOUR_MS, "1", asset="ABC", network="conversion", to="kucoin"),
            rebal(S + 3 * HOUR_MS, "9", status="blocked"),
        ),
    )


# ------------------------------------------------------------------ formulas


def test_tax_applies_to_gains_and_never_refunds_a_loss() -> None:
    assert after_tax(D(100), D("0.35")) == D(65)
    assert after_tax(D(-100), D("0.35")) == D(-100)
    assert after_tax(D(100), None) == D(100)


def test_monthly_scaling_and_percent() -> None:
    assert per_month(D(10), D("15.21875")) == D(20)
    assert pct_per_month(D(10), D("15.21875"), D(1000)) == D(2)
    assert per_month(D(10), D(0)) == D(0)
    assert pct_per_month(D(10), D(1), D(0)) == D(0)
    assert window_days(0, 3 * DAY_MS // 2) == D("1.5")
    assert window_days(5, 1) == D(0)


# ------------------------------------------------------------------ equity


def test_snapshot_at_is_the_last_one_at_or_before() -> None:
    a, b = SnapshotSet(10, ()), SnapshotSet(20, ())
    assert snapshot_at((a, b), 9) is None
    assert snapshot_at((a, b), 10) is a
    assert snapshot_at((a, b), 19) is a
    assert snapshot_at((a, b), 20) is b


def test_untouched_capital_is_cash_before_any_snapshot() -> None:
    v = valuation_at(tiny(), S)
    assert (v.equity, v.non_usdt, v.seeded) == (D(1000), D(0), D(0))


def test_unseeded_capital_counts_as_cash_in_equity() -> None:
    v = valuation_at(tiny(), S + 2 * HOUR_MS)
    assert v.equity == D(600) + D(200) + (D(1000) - D(650))
    assert v.non_usdt == D(200)
    assert v.seeded == D(650)
    assert v.unseeded_coin == D(0)


def test_stranded_coin_is_the_unseeded_non_usdt_balance() -> None:
    stray = HoldingPoint("binance", "ABC", D(10), D(3), D(0))
    data = replace(tiny(), snapshots=(SnapshotSet(S, (usdt("binance", "500", "500"), stray)),))
    assert valuation_at(data, S).unseeded_coin == D(30)


def test_transfers_in_flight_at_the_snapshot_are_added_blocked_and_conversions_are_not() -> None:
    held = (usdt("binance", "500", "500"), abc("kucoin", "10", "2", "2"))
    snaps = (SnapshotSet(S + 20, held), SnapshotSet(S + 110, held))
    flights = (
        rebal(S + 10, "1", amount="100", fee="1", arrives=S + 100),
        rebal(S + 10, "1", asset="ABC", amount="5", fee="1", arrives=S + 100, to="kucoin"),
        rebal(S + 10, "1", amount="300", status="blocked", arrives=S + 100),
        rebal(S + 10, "1", network="conversion", amount="300", arrives=S + 100),
    )
    data = SetData("t", run(), snapshots=snaps, rebalances=flights)
    # 500 + 20 held + 480 unseeded cash; the in-flight USDT (99) and ABC (4 x 2) are on top
    inside, after = valuation_at(data, S + 50), valuation_at(data, S + 120)
    assert after.equity == D(500) + D(20) + D(480)
    assert inside.equity == after.equity + D(99) + D(4) * D(2)
    assert inside.non_usdt == D(20) + D(8)
    # a late arrival commit: the snapshot before the arrival still counts the transfer
    late = SetData("t", run(), snapshots=snaps[:1], rebalances=flights)
    assert valuation_at(late, S + 105).equity == inside.equity


def test_daily_times_and_drawdown() -> None:
    start = S + 10 * HOUR_MS
    assert daily_times(start, start + 2 * DAY_MS) == [
        start, S + DAY_MS, S + 2 * DAY_MS, start + 2 * DAY_MS,
    ]  # fmt: skip
    assert daily_times(5, 5) == [5]
    assert max_drawdown_pct([D(100), D(120), D(90), D(110)], D(1000)) == D(3)
    assert max_drawdown_pct([], D(1000)) == D(0)
    assert max_drawdown_pct([D(1)], D(0)) == D(0)


# ------------------------------------------------------------------ window stats


def test_liquidation_reserve_is_the_exit_cost_of_inventory_at_window_end() -> None:
    inventory = (usdt("binance", "600", "500"), abc("kucoin", "100", "2", "1.5"))
    snaps = (SnapshotSet(S + HOUR_MS, inventory), SnapshotSet(S + 2 * HOUR_MS, inventory))
    data = SetData("t", run(), snapshots=snaps)
    held = window_stats(data, S + HOUR_MS, S + 3 * HOUR_MS, LIQ)  # 200 held at start AND end
    assert held.liq_cost == D("0.6")  # the old delta rule charged 0
    falling = (
        SnapshotSet(S + HOUR_MS, inventory),
        SnapshotSet(S + 2 * HOUR_MS, (usdt("binance", "800", "500"),)),
    )
    sold = window_stats(SetData("t", run(), snapshots=falling), S + HOUR_MS, S + 3 * HOUR_MS, LIQ)
    assert sold.liq_cost == D(0)  # never a credit when the inventory shrinks


def test_window_stats_hand_computed() -> None:
    s = window_stats(tiny(), S, S + DAY_MS, LIQ)
    assert s.trades_executed == 2
    assert s.realized == D(50)
    assert (s.rebal_transfer, s.rebal_conversion, s.rebal_costs) == (D(4), D(1), D(5))
    assert s.conversions_count == 1
    assert s.rebalances_blocked == 1  # blocked rows never cost anything
    assert s.hedged == D(45)
    assert (s.equity_start, s.equity_end, s.total) == (D(1000), D(1150), D(150))
    assert s.mtm == D(105)  # 150 - 50 + 5
    assert s.liq_cost == D("0.6")  # 200 non-USDT x 0.3 %
    assert s.total_liq == D("149.4")
    assert s.skips == (("spread_gone", 1),)  # the second skip is outside the window
    assert s.avg_notional_usd == D(100)
    assert s.mtm_share == D(105) / (D(45) + D(105))
    assert s.mtm_dominated  # 105 of 150
    assert s.unseeded_coin_value_usd == D(0)
    assert s.days == D(1)


def test_headline_numbers_per_tax_rate() -> None:
    s = window_stats(tiny(), S, S + DAY_MS, LIQ)
    rate = D("0.35")
    assert s.net_usd_month(None) == D("149.4") * D("30.4375")
    assert s.net_usd_month(rate) == D("97.11") * D("30.4375")
    assert s.net_pct_month(rate) == D("97.11") * D("30.4375") / D(1000) * 100


def test_deployed_capital_is_time_weighted() -> None:
    s = window_stats(tiny(), S, S + DAY_MS, LIQ)
    assert s.deployed_avg == D(650) * 23 / 24
    assert s.idle_avg == D(1000) - s.deployed_avg


def test_cap_counters_and_sweep_gaps() -> None:
    caps = (
        CapHour(S + 0 * HOUR_MS, 100, 10, 30, 2),
        CapHour(S + 1 * HOUR_MS, 100, 0, 0, 0),
        CapHour(S + 3 * HOUR_MS, 0, 0, 0, 0),  # a row without sweeps is still a gap
        CapHour(S + 4 * HOUR_MS, 50, 5, 9, 1),
    )
    data = replace(tiny(), caps=caps)
    s = window_stats(data, S, S + 6 * HOUR_MS, LIQ)
    assert (s.sweeps, s.sweeps_cap_bound, s.dropped_routes, s.alerts_cap_excluded) == (
        250, 15, 39, 3,
    )  # fmt: skip
    assert s.cap_bound_pct == D(15) / D(250) * 100
    assert (s.gap_hours, s.window_hours) == (3, 6)  # hours 2, 3 and 5
    assert s.gap_days == ("2026-11-01",)
    assert s.gap_share == D("0.5")


def test_exhausted_share_counts_all_attempts() -> None:
    skips = (
        SkipRecord(S + 1, "coin_budget_exhausted"),
        SkipRecord(S + 2, "coin_budget_exhausted"),
        SkipRecord(S + 5, "spread_gone"),
    )
    s = window_stats(replace(tiny(), skips=skips), S, S + DAY_MS, LIQ)
    assert s.exhausted_share == D(2) / D(5)  # 2 executed + 3 skips


def test_empty_set_and_zero_length_window_do_not_crash() -> None:
    data = SetData("e", run())
    s = window_stats(data, S, S + DAY_MS, LIQ)
    assert (s.total, s.total_liq, s.trades_executed) == (D(0), D(0), 0)
    assert s.avg_notional_usd is None
    assert s.mtm_share is None
    assert s.cap_bound_pct is None
    assert s.net_pct_month(D("0.35")) == D(0)
    assert s.exhausted_share == D(0)
    zero = window_stats(data, S, S, LIQ)
    assert zero.days == D(0)
    assert zero.net_pct_month(None) == D(0)
    assert zero.gap_share == D(0)


def test_loss_window_is_not_refunded_by_tax() -> None:
    snap = SnapshotSet(S + HOUR_MS, (usdt("binance", "900", "1000"),))
    s = window_stats(SetData("l", run(), snapshots=(snap,)), S, S + DAY_MS, LIQ)
    assert s.total == D(-100)
    assert s.net_usd_month(D("0.35")) == s.net_usd_month(None) == D(-100) * D("30.4375")


# ------------------------------------------------------------------ windows


def test_twenty_days_are_not_enough_twenty_one_are() -> None:
    short = split_window(S, S + 20 * DAY_MS)
    assert not short.sufficient
    assert short.periods == ()
    assert short.holdout_days == D(13)
    assert short.days_missing == D(1)
    ok = split_window(S, S + 21 * DAY_MS)
    assert ok.sufficient
    assert ok.tuning_end_ms == S + 7 * DAY_MS
    assert ok.periods == ((S + 7 * DAY_MS, S + 14 * DAY_MS), (S + 14 * DAY_MS, S + 21 * DAY_MS))
    assert ok.days_missing == D(0)
    assert ok.total_days == D(21)


def test_tuning_is_a_third_rounded_up_to_midnight_and_periods_are_capped_at_four() -> None:
    sp = split_window(S, S + 60 * DAY_MS)
    assert sp.tuning_end_ms == S + 20 * DAY_MS
    assert len(sp.periods) == 4
    assert [(b - a) // DAY_MS for a, b in sp.periods] == [10, 10, 10, 10]
    assert sp.periods[0][0] == sp.tuning_end_ms
    assert sp.periods[-1][1] == S + 60 * DAY_MS
    odd = split_window(S + 5 * HOUR_MS, S + 5 * HOUR_MS + 31 * DAY_MS)
    assert odd.tuning_end_ms % DAY_MS == 0  # boundaries sit on UTC midnights
    assert odd.sufficient


def test_period_edges_are_contiguous_and_cover_the_holdout() -> None:
    sp = split_window(S, S + 28 * DAY_MS)  # tuning 10 d (28/3 rounded up), holdout 18 d -> k = 2
    assert sp.tuning_end_ms == S + 10 * DAY_MS
    assert [(a - S) // DAY_MS for a, _ in sp.periods] == [10, 19]
    assert sp.periods[-1][1] == S + 28 * DAY_MS


def test_single_period_holdout_is_insufficient() -> None:
    sp = split_window(S, S + 20 * DAY_MS)  # 13 days = one 7-day period only
    assert not sp.sufficient
    assert split_window(S, S).periods == ()
    assert split_window(S, S - 5).total_days == D(0)


# ------------------------------------------------------------------ concentration


def conc_set() -> SetData:
    trades = (
        trade(S + 1 * HOUR_MS, "10", "ABC/USDT", "binance", "kucoin"),
        trade(S + 2 * HOUR_MS, "6", "DEF/USDT", "binance", "okx"),
        trade(S + 3 * HOUR_MS, "2", "GHI/USDT", "kucoin", "okx"),
        trade(S + 4 * HOUR_MS, "-1", "JKL/USDT", "okx", "binance"),
    )
    rebs = (
        rebal(S + 5 * HOUR_MS, "2", asset="USDT", to="binance"),  # R1, R2 share 1 + 1
        rebal(S + 5 * HOUR_MS, "0.5", asset="ABC", to="kucoin", src="binance"),  # R1
        rebal(S + 5 * HOUR_MS, "0.3", asset="GHI", to="okx", network="conversion", src="okx"),
        rebal(S + 5 * HOUR_MS, "0.2", asset="USDT", to="gateio"),  # no route buys there
        rebal(S + 5 * HOUR_MS, "7", asset="USDT", to="binance", status="blocked"),
    )
    snap = SnapshotSet(S + 6 * HOUR_MS, (usdt("binance", "1100", "1000"),))
    return SetData("c", run(), snapshots=(snap,), trades=trades, rebalances=rebs)


def test_concentration_attributes_rebalance_costs_by_asset_and_venue() -> None:
    c = concentration(conc_set(), S, S + DAY_MS, LIQ)
    nets = dict(c.route_net)
    assert nets["ABC/USDT|binance>kucoin"] == D("8.5")  # 10 - 1 - 0.5
    assert nets["DEF/USDT|binance>okx"] == D(5)
    assert nets["GHI/USDT|kucoin>okx"] == D("1.7")  # conversion of GHI sold on okx
    assert nets["JKL/USDT|okx>binance"] == D(-1)
    assert c.unattributed_rebal == D("0.2")  # blocked rows are ignored entirely
    assert dict(c.coin_net)["ABC"] == D("8.5")
    positive = D("15.2")
    assert c.top1_route_share == D("8.5") / positive
    assert c.top2_route_share == D("13.5") / positive
    assert c.hhi_routes == sum(((D(x) / positive) ** 2 for x in ("8.5", "5", "1.7")), D(0))
    assert c.top_routes == ("ABC/USDT|binance>kucoin", "DEF/USDT|binance>okx")
    assert c.top_coins == ("ABC", "DEF")


def test_ex_top_two_recompute_removes_realized_and_attributed_rebalance() -> None:
    c = concentration(conc_set(), S, S + DAY_MS, LIQ)
    # equity 1100 + (1000 - 1000 seeded... ) -> total 100 (cash 1100 vs capital 1000), no coin
    assert c.total_liq_ex_routes == D(100) - D("13.5")
    assert c.total_liq_ex_coins == D(100) - D("13.5") - D(0)
    assert c.pct_ex_routes(None) == pct_per_month(D("86.5"), D(1), D(1000))
    assert c.pct_ex_coins(D("0.35")) == pct_per_month(D("86.5") * D("0.65"), D(1), D(1000))


def test_coin_mtm_is_quantity_times_price_change_between_snapshots() -> None:
    cash = usdt("binance", "500", "500")
    snaps = (
        SnapshotSet(S + HOUR_MS, (cash, abc("kucoin", "10", "1", "1"))),
        SnapshotSet(S + 2 * HOUR_MS, (cash, abc("kucoin", "10", "1.2", "1"))),
        SnapshotSet(S + 3 * HOUR_MS, (cash, abc("kucoin", "20", "1.1", "1"))),
    )
    data = SetData("m", run(), snapshots=snaps)
    # 10 x (1.2 - 1.0) + 10 x (1.1 - 1.2) over [t1, t3]
    assert coin_mtm(data, S + HOUR_MS, S + 3 * HOUR_MS) == {"ABC": D("1.0")}
    assert coin_mtm(data, S, S + HOUR_MS) == {}  # no snapshot before the window start


def test_coin_attribution_falls_back_to_any_route_of_the_coin() -> None:
    trades = (trade(S + HOUR_MS, "10", "ABC/USDT", "binance", "kucoin"),)
    stray = rebal(S + 2 * HOUR_MS, "1", asset="ABC", to="okx", src="kucoin")
    c = concentration(SetData("f", run(), trades=trades, rebalances=(stray,)), S, S + DAY_MS, LIQ)
    assert dict(c.route_net) == {"ABC/USDT|binance>kucoin": D(9)}


def test_zero_notional_trades_share_a_cost_equally() -> None:
    trades = (
        trade(S + HOUR_MS, "5", "ABC/USDT", "binance", "kucoin", notional="0"),
        trade(S + HOUR_MS, "5", "DEF/USDT", "binance", "okx", notional="0"),
    )
    c = concentration(
        SetData("z", run(), trades=trades, rebalances=(rebal(S + 2 * HOUR_MS, "2"),)),
        S, S + DAY_MS, LIQ,
    )  # fmt: skip
    assert dict(c.route_net) == {"ABC/USDT|binance>kucoin": D(4), "DEF/USDT|binance>okx": D(4)}


def test_fewer_than_two_positive_routes_and_no_trades() -> None:
    one = SetData(
        "o", run(), trades=(trade(S + HOUR_MS, "3"), trade(S + HOUR_MS, "-4", "XYZ/USDT"))
    )
    c = concentration(one, S, S + DAY_MS, LIQ)
    assert c.top_routes == ("ABC/USDT|binance>kucoin",)
    assert c.top1_route_share == c.top2_route_share == D(1)
    empty = concentration(SetData("e", run()), S, S + DAY_MS, LIQ)
    assert empty.top_routes == ()
    assert empty.top1_route_share == D(0)
    assert empty.hhi_routes == D(0)
    losing = concentration(
        SetData("n", run(), trades=(trade(S + HOUR_MS, "-4"),)), S, S + DAY_MS, LIQ
    )
    assert losing.top_routes == ()
    assert losing.top2_route_share == D(0)


# ------------------------------------------------------------------ analysis


def test_analysis_of_a_short_window_is_a_preview_without_holdout() -> None:
    a = analyze_set(tiny(), S + DAY_MS, LIQ)
    assert a.holdout is None
    assert a.tuning is None
    assert a.periods == ()
    assert a.focus is a.full
    assert not a.focus_is_holdout
    assert not a.split.sufficient


def test_analysis_with_a_long_window_splits_tuning_holdout_and_periods() -> None:
    data = replace(tiny(), run=run(S))
    a = analyze_set(data, S + 30 * DAY_MS, LIQ)
    assert a.holdout is not None
    assert a.tuning is not None
    assert a.focus is a.holdout
    assert a.focus_is_holdout
    assert len(a.periods) == 2
    assert a.tuning.b_ms == a.holdout.a_ms == a.periods[0].a_ms
    assert a.periods[-1].b_ms == a.holdout.b_ms == S + 30 * DAY_MS
    assert a.conversion_cost_share is None  # no rebalance inside the holdout


def test_conversion_cost_share_of_the_focus_window() -> None:
    a = analyze_set(tiny(), S + DAY_MS, LIQ)
    assert a.conversion_cost_share == D(1) / D(5)


def test_a_replaced_run_drops_its_first_ten_minutes() -> None:
    previous = RunInfo(0, S - DAY_MS, ("binance",), D(1000), "old")
    data = SetData("r", run(), previous_runs=(previous,))
    assert data.window_start_ms == S + 10 * 60_000
    assert SetData("r", run()).window_start_ms == S


def test_analysis_before_the_window_starts_has_no_data() -> None:
    a = analyze_set(SetData("e", run()), S - DAY_MS, LIQ)
    assert a.full.days == D(0)
    assert a.split.days_missing == D(14)


def test_common_window_is_cut_at_the_latest_start() -> None:
    early, late = tiny(), replace(tiny(), name="late", run=run(S + 10 * DAY_MS))
    cw = common_window([early, late], S + 40 * DAY_MS, LIQ)
    assert cw is not None
    assert cw.basis == "holdout"
    assert cw.start_ms > S + 10 * DAY_MS
    assert [name for name, _ in cw.rows] == ["t", "late"]
    assert all(stats.a_ms == cw.start_ms for _, stats in cw.rows)
    preview = common_window([early, late], S + 12 * DAY_MS, LIQ)
    assert preview is not None
    assert preview.basis == "preview"
    assert preview.start_ms == S + 10 * DAY_MS
    assert common_window([], S, LIQ) is None
