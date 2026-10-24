"""Markdown rendering of the GO report (pure string building)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from nexus.reports.go_build import GoReport, Metric, window_metrics
from nexus.reports.go_math import (
    GO_BAR_PCT,
    GO_TAX_RATE,
    TAX_RATES,
    SetAnalysis,
    WindowStats,
    after_tax,
    pct_per_month,
)
from nexus.reports.go_verdict import RateEvaluation, Verdict

NA = "n/a"


def fmt_ts(ms: int) -> str:
    """UTC minute precision."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%MZ")


def fmt_date(ms: int) -> str:
    """UTC date."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def fmt(metric: Metric) -> str:
    """Presentation of one metric (rounding happens only here)."""
    value = metric.value
    if value is None:
        return NA
    if isinstance(value, bool):
        return "YES" if value else "no"
    if metric.kind == "usd" and isinstance(value, Decimal):
        return f"{value:,.2f}"
    if metric.kind == "pct" and isinstance(value, Decimal):
        return f"{value:.2f} %"
    if metric.kind == "share" and isinstance(value, Decimal):
        return f"{value:.3f}"
    if metric.kind == "num" and isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def _pct(value: Decimal) -> str:
    return f"{value:.2f} %"


def _ok(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    def cell(text: str) -> str:
        return text.replace("|", "\\|")  # route keys and |mtm| contain pipes

    lines = [
        "| " + " | ".join(cell(h) for h in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return lines


def _verdict_section(report: GoReport) -> list[str]:
    v = report.verdict
    if v is None:
        return [f"**GO set `{report.go_set}` has no run in the database: no verdict.**", ""]
    lines = [
        f"## Verdict for GO set `{v.set_name}`: **{v.label}**",
        "",
        f"- Tax rate of the verdict: {GO_TAX_RATE * 100:.0f} % (15 % shown next to it); "
        f"bar: >= {GO_BAR_PCT} % per month on fixed capital, holdout only.",
        f"- Confidence: **{v.confidence}**.",
    ]
    lines += [f"- Reason: {r}" for r in v.reasons]
    if v.open_gates:
        lines.append(
            f"- Open gates: {', '.join(v.open_gates)} (`docs/legal/go-gates-checklist.md`)."
        )
    for flag in v.flags:
        lines.append(f"- Flag{' (BLOCKING)' if flag.blocking else ''}: {flag.text}")
    lines += ["", "**What would refute it**", ""]
    lines += [f"- {line}" for line in v.refute]
    lines.append("")
    lines += _gate_table(v)
    return lines


def _gate_table(v: Verdict) -> list[str]:
    if v.at_35 is None or v.at_15 is None:
        return []
    e35, e15 = v.at_35, v.at_15
    probes: list[tuple[str, Callable[[RateEvaluation], tuple[bool, str]]]] = [
        ("holdout net %/month >= 2.0", lambda e: (e.money_ok, _pct(e.aggregate_pct))),
        (
            "every period > 0",
            lambda e: (e.periods_positive, ", ".join(_pct(p) for p in e.period_pcts)),
        ),
        (
            "periods >= 2.0 (ceil(k/2))",
            lambda e: (
                e.periods_at_bar_ok,
                f"{e.periods_at_bar} of {e.periods_at_bar_needed} needed",
            ),
        ),
        (
            "no period > 60 % of positive net",
            lambda e: (e.share_ok, f"max {e.max_period_share * 100:.0f} %"),
        ),
        ("ex-top-2 routes >= 2.0", lambda e: (e.ex_routes_ok, _pct(e.ex_routes_pct))),
        ("ex-top-2 coins >= 2.0", lambda e: (e.ex_coins_ok, _pct(e.ex_coins_pct))),
    ]
    rows = [_gate_row(name, e35, e15, probe) for name, probe in probes]
    return ["**Gates on the holdout**", "", *_table(["gate", "35 % tax", "15 % tax"], rows), ""]


def _gate_row(
    name: str,
    e35: RateEvaluation,
    e15: RateEvaluation,
    probe: Callable[[RateEvaluation], tuple[bool, str]],
) -> list[str]:
    ok35, text35 = probe(e35)
    ok15, text15 = probe(e15)
    return [name, f"{_ok(ok35)} ({text35})", f"{_ok(ok15)} ({text15})"]


def _overview(report: GoReport) -> list[str]:
    rows = []
    for a in report.analyses:
        s = a.focus
        rows.append(
            [
                f"`{a.name}`",
                fmt_ts(a.data.run.started_ms),
                f"{a.full.days:.1f}",
                "holdout" if a.focus_is_holdout else "preview (in-sample)",
                str(s.trades_executed),
                _pct(s.net_pct_month(None)),
                _pct(s.net_pct_month(TAX_RATES[0])),
                _pct(s.net_pct_month(GO_TAX_RATE)),
                f"{s.net_usd_month(GO_TAX_RATE):,.2f}",
                "YES" if s.mtm_dominated else "no",
            ]
        )
    header = ["set", "since", "days", "basis", "trades", "pre-tax %/mo", "15 % %/mo",
              "35 % %/mo", "35 % $/mo", "MTM-dom."]  # fmt: skip
    return ["## Overview", "", *_table(header, rows), ""]


def _set_section(report: GoReport, a: SetAnalysis) -> list[str]:
    run = a.data.run
    role = "GO set" if a.name == report.go_set else "context only, no best-of selection"
    lines = [f"## Set `{a.name}` ({role})", ""]
    ident = [
        ["venues", ", ".join(run.venues) or NA],
        ["run_id / config_hash", f"{run.run_id} / `{run.config_hash[:16]}`"],
        ["since (run start)", fmt_ts(run.started_ms)],
        ["window used", f"{fmt_ts(a.start_ms)} .. {fmt_ts(a.until_ms)} ({a.full.days:.2f} days)"],
        ["capital_fixed", f"{run.capital_usd:,.2f}"],
    ]
    if a.data.previous_runs:
        prior = "; ".join(
            f"run {r.run_id} from {fmt_ts(r.started_ms)} (`{r.config_hash[:8]}`)"
            for r in a.data.previous_runs
        )
        ident.append(["earlier runs (replaced; not in the window)", prior])
        ident.append(["first 10 min of this run", "excluded (rolling-deploy overlap, N13)"])
    ops = report.ops.get(a.name)
    ident.append(
        [
            "timed_out_pct (N2)",
            f"{ops.timed_out_pct} %" if ops and ops.timed_out_pct is not None else "not supplied",
        ]
    )
    missing = ops.membership_missing if ops else None
    ident.append(["membership_missing (N6)", NA if missing is None else str(missing)])
    lines += [*_table(["field", "value"], ident), ""]

    columns: list[tuple[str, WindowStats]] = [("full own window", a.full)]
    if a.tuning is not None and a.holdout is not None:
        columns += [("tuning (in-sample)", a.tuning), ("HOLDOUT (GO numbers)", a.holdout)]
    else:
        lines.append(
            f"> Holdout not available: {a.split.days_missing:.1f} more days needed "
            "(tuning >= 7 d + holdout >= 14 d). Numbers below are an in-sample preview, "
            "not a verdict basis."
        )
        lines.append("")
    per_column = [window_metrics(stats) for _, stats in columns]
    rows = [
        [first.label, *[fmt(col[i]) for col in per_column]] for i, first in enumerate(per_column[0])
    ]
    lines += _table(["field", *[name for name, _ in columns]], rows)
    lines.append("")
    lines += _stability(a)
    lines += _concentration(a)
    return lines


def _stability(a: SetAnalysis) -> list[str]:
    if not a.periods:
        return [
            "**Stability (B5)**: needs a holdout of >= 14 days (k >= 2 periods of >= 7 days).",
            "",
        ]
    rows = []
    for i, p in enumerate(a.periods, 1):
        s = p.stats
        rows.append(
            [
                str(i),
                f"{fmt_date(p.a_ms)} .. {fmt_date(p.b_ms)}",
                f"{s.days:.1f}",
                f"{s.total_liq:,.2f}",
                _pct(s.net_pct_month(None)),
                _pct(s.net_pct_month(TAX_RATES[0])),
                _pct(s.net_pct_month(GO_TAX_RATE)),
            ]
        )
    header = ["period", "dates", "days", "total after liq $", "pre-tax %/mo", "15 %", "35 %"]
    return [
        f"**Stability (B5): {len(a.periods)} consecutive holdout periods**",
        "",
        *_table(header, rows),
        "",
    ]


def _concentration(a: SetAnalysis) -> list[str]:
    c = a.concentration
    basis = "holdout" if a.focus_is_holdout else "full window (preview)"
    c_route = f"{c.top1_route_share * 100:.1f} % / {c.top2_route_share * 100:.1f} %"
    c_coin = f"{c.top1_coin_share * 100:.1f} % / {c.top2_coin_share * 100:.1f} %"
    rows = [
        ["top1 / top2 route share", c_route],
        ["top1 / top2 coin share", c_coin],
        ["HHI over routes", f"{c.hhi_routes:.3f}"],
        ["top-2 routes", ", ".join(f"`{r}`" for r in c.top_routes) or NA],
        ["top-2 coins", ", ".join(c.top_coins) or NA],
        ["net %/mo after 35 % tax, without top-2 routes", _pct(c.pct_ex_routes(GO_TAX_RATE))],
        [
            "net %/mo after 35 % tax, without top-2 coins (incl. MTM)",
            _pct(c.pct_ex_coins(GO_TAX_RATE)),
        ],
        ["rebalance cost not attributable to any route", f"{c.unattributed_rebal:,.2f}"],
    ]
    return [
        f"**Concentration (B6), basis: {basis}** (strict rule: both ex-top-2 results must stay "
        f">= {GO_BAR_PCT} % after 35 % tax; filter inside one set, B14-style approximation)",
        "",
        *_table(["field", "value"], rows),
        "",
    ]


def _comparison(report: GoReport) -> list[str]:
    c = report.common
    if c is None:
        return []
    rows = []
    base = dict(c.rows).get("all")
    for name, s in c.rows:
        delta = (
            _pct(s.net_pct_month(GO_TAX_RATE) - base.net_pct_month(GO_TAX_RATE))
            if base is not None and name != "all"
            else NA
        )
        rows.append(
            [
                f"`{name}`",
                str(s.trades_executed),
                _pct(s.net_pct_month(None)),
                _pct(s.net_pct_month(TAX_RATES[0])),
                _pct(s.net_pct_month(GO_TAX_RATE)),
                delta,
            ]
        )
    return [
        "## Venue-access value on the common window",
        "",
        f"Common window {fmt_ts(c.start_ms)} .. {fmt_ts(c.until_ms)}, basis: **{c.basis}**"
        + (" (in-sample preview)" if c.basis == "preview" else "")
        + ". The difference to `all` is the value of the venues a set excludes "
        "(Bybit / gateio / conditional venues).",
        "",
        *_table(["set", "trades", "pre-tax %/mo", "15 %", "35 %", "35 % minus `all`"], rows),
        "",
    ]


def _fees(report: GoReport) -> list[str]:
    lines = [
        "- **Fee source (F2)**: per-venue taker fees come from live exchange metadata, fetched at "
        "runtime and applied per trade. They are NOT part of the run hash (fee tiers are "
        "exchange-side facts), so a fee-tier change inside the window is not visible as a new "
        "run. No fee-table snapshot is stored at run start; the per-trade fee breakdown is "
        "persisted in `spread_evaluations` (profitable rows are kept indefinitely), and the "
        "observed effective rates are listed below."
    ]
    if report.fees:
        rows = [
            [f.venue, str(f.samples), _pct(f.avg_pct), _pct(f.min_pct), _pct(f.max_pct)]
            for f in report.fees
        ]
        lines += ["", *_table(["venue", "evaluations", "avg fee %", "min", "max"], rows), ""]
    else:
        lines.append(
            "- Observed fee table: not available (no profitable evaluations in the window)."
        )
    return lines


def _disclosures(report: GoReport) -> list[str]:
    lines = ["## Disclosures", ""]
    lines += _fees(report)
    conv_notes = [
        f"`{a.name}`: conversion share of rebalance costs {a.conversion_cost_share * 100:.0f} %"
        f", net %/mo after 35 % tax with conversion cost doubled "
        f"{_pct(pct_per_month(_doubled(a), a.focus.days, a.focus.capital))}"
        for a in report.analyses
        if a.conversion_cost_share is not None and a.conversion_cost_share > Decimal("0.1")
    ]
    lines += [
        "- **Accrual / `since`**: data for a set exists only from its run start (`since`); no "
        "backfill. A changed run definition or strategy parameter starts a new run with fresh "
        "capital and a new `since`; earlier runs are listed per set but never mixed into a window. "
        "Comparisons between sets use only the common window.",
        "- **Parameters**: only the run hash is stored, not the parameter values; the dates of "
        "parameter changes are the run starts listed per set. Any parameter chosen by looking "
        "at data may only use the tuning part (holdout restarts from a change).",
        "- **Tuning vs holdout**: chronological, tuning = first third (min 7 days), holdout = rest "
        "(min 14 days, k = floor(holdout/7) <= 4 equal periods); boundaries are rounded up to UTC "
        "midnights so that equity at an edge is an end-of-day state. GO numbers are holdout only.",
        "- **Tax model**: tax = rate x max(window total, 0), losses are not refunded; rates "
        "15 % and 35 % shown, the verdict uses 35 %. Final tax position is open (G3, accountant).",
        f"- **Liquidation reserve**: non-USDT inventory is charged a flat {report.liq_cost_pct} % "
        "exit cost (taker fee + half spread approximation, same as the paper conversion cost, "
        "N11); venue-specific spreads are not stored. It is subtracted from the headline.",
        "- **Hedge**: no hedge cost is modelled; `hedged` is a reference, never the headline.",
        "- **N1 shared alert gating**: paper trades fire on shared alerts; a route that opened "
        "its episode while only a smaller set held it in its top-N is not re-alerted for `all` "
        "(downward bias on `all` only; bounded by `alerts cap-excluded`).",
        "- **N2 shared evaluation deadline**: timeouts hit all sets; the share is read from logs "
        "(supplied via the ops file), not from the database.",
        "- **N3 equal split**: the same $ per set is split equally over its venues; smaller sets "
        "get deeper inventory per venue and idle capital sits on rarely used venues (shown as "
        "deployed vs idle capital).",
        "- **N4 trade size**: realised average notional is shown per window; scaling claims must "
        "use it (the target notional is capped by the coin slot).",
        "- **N5 MTM**: about half of the capital sits in alt inventory; MTM is shown "
        "separately and flagged when it dominates.",
        "- **N6**: `membership_missing` is not persisted; supplied from logs when available.",
        "- **N9 idle clock**: the slot idle clock resets on a restart (conservative; shows up as "
        "`coin_budget_exhausted`).",
        "- **N10 stranded coin**: unseeded coin value at window end is shown; it is already inside "
        "the liquidation reserve.",
        "- **N12 per-set heartbeat**: hours without a sweep come from `paper_cap_stats`; days with "
        "gaps are listed, nothing is removed.",
        "- **N13 rolling deploy**: when a run replaced an earlier one, its first 10 minutes are "
        "excluded from the window.",
        "- **Snapshots**: equity uses the last balance snapshot at or before each instant "
        "(hourly resolution in the query, daily after retention thinning); per-coin MTM for the "
        "ex-top-2-coins test is an approximation at that granularity.",
        "- **Regime**: BTC volatility per period is not stored; regimes come from the ops file. "
        "Unknown or a single regime caps the confidence at `low`.",
        "- **Concentration** is a filter inside one set (B14-style approximation, likely "
        "conservative); rebalance costs are attributed by asset and destination venue pro rata to "
        "trade notional.",
    ]
    if conv_notes:
        lines.append(
            "- **N11 conversion cost** above 10 % of rebalance costs: "
            + "; ".join(conv_notes)
            + "."
        )
    return lines


def _doubled(a: SetAnalysis) -> Decimal:
    """Focus-window total after liquidation and 35 % tax with conversion costs paid twice."""
    return after_tax(a.focus.total_liq - a.focus.rebal_conversion, GO_TAX_RATE)


def render_markdown(report: GoReport) -> str:
    """The complete report."""
    head = [
        f"# Nexus GO report - data until {fmt_date(report.until_ms)} (last complete UTC day)",
        "",
        "Paper simulation only: no orders, transfers or keys are involved (ADR 0001). All money "
        "is USD on a fixed virtual capital per set.",
        "",
    ]
    body = [
        *head,
        *_verdict_section(report),
        *_overview(report),
        *_comparison(report),
    ]
    for a in report.analyses:
        body += _set_section(report, a)
    body += _disclosures(report)
    return "\n".join(body).rstrip() + "\n"


__all__ = ["fmt", "fmt_date", "fmt_ts", "render_markdown"]
