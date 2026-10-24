"""Assemble the GO report model (pure) and flatten it for Markdown/JSON output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from nexus.reports.go_math import (
    DEFAULT_LIQ_COST_PCT,
    GO_TAX_RATE,
    TAX_RATES,
    CommonWindow,
    SetAnalysis,
    SetData,
    WindowStats,
    analyze_set,
    common_window,
)
from nexus.reports.go_verdict import GateStatus, OpsInputs, Verdict, decide

REPORT_VERSION = 1


@dataclass(frozen=True, slots=True)
class FeeObservation:
    """Effective taker-fee % observed on profitable evaluations of one venue (F2 disclosure)."""

    venue: str
    samples: int
    avg_pct: Decimal
    min_pct: Decimal
    max_pct: Decimal


@dataclass(frozen=True, slots=True)
class GoReport:
    """Everything the renderers need."""

    until_ms: int
    go_set: str
    liq_cost_pct: Decimal
    gates: GateStatus
    analyses: tuple[SetAnalysis, ...]
    common: CommonWindow | None
    verdict: Verdict | None
    ops: Mapping[str, OpsInputs]
    fees: tuple[FeeObservation, ...]


def build_report(
    datas: Sequence[SetData],
    *,
    until_ms: int,
    go_set: str,
    gates: GateStatus | None = None,
    ops: Mapping[str, OpsInputs] | None = None,
    fees: Sequence[FeeObservation] = (),
    liq_cost_pct: Decimal = DEFAULT_LIQ_COST_PCT,
) -> GoReport:
    """Analyse every set, compare them on the common window, decide the GO set's verdict."""
    gates = gates or GateStatus()
    ops = dict(ops or {})
    analyses = tuple(analyze_set(d, until_ms, liq_cost_pct) for d in datas)
    by_name = {a.name: a for a in analyses}
    chosen = by_name.get(go_set)
    verdict = decide(chosen, gates, ops.get(go_set)) if chosen is not None else None
    return GoReport(
        until_ms=until_ms,
        go_set=go_set,
        liq_cost_pct=liq_cost_pct,
        gates=gates,
        analyses=analyses,
        common=common_window(datas, until_ms, liq_cost_pct),
        verdict=verdict,
        ops=ops,
        fees=tuple(fees),
    )


# --------------------------------------------------------------------------- flattening


@dataclass(frozen=True, slots=True)
class Metric:
    """One report field: machine key, label, raw value and the presentation kind."""

    key: str
    label: str
    value: object
    kind: str
    """``usd`` | ``pct`` | ``int`` | ``share`` | ``num`` | ``text`` | ``flag``."""


def _skips(stats: WindowStats) -> str:
    return ", ".join(f"{reason}={n}" for reason, n in stats.skips) or "none"


def window_metrics(stats: WindowStats) -> list[Metric]:
    """The per-window B4 fields (one table column per window)."""
    pre, t15, t35 = None, TAX_RATES[0], GO_TAX_RATE
    m = Metric
    return [
        m("window_days", "window days", stats.days, "num"),
        m("capital_fixed", "fixed capital", stats.capital, "usd"),
        m("deployed_capital_avg", "deployed capital (time-weighted)", stats.deployed_avg, "usd"),
        m("idle_capital_avg", "idle capital (cash, 0 %)", stats.idle_avg, "usd"),
        m("trades_executed", "trades executed", stats.trades_executed, "int"),
        m("trades_skipped", "trades skipped", stats.skipped_total, "int"),
        m("skips_by_reason", "skips by reason", _skips(stats), "text"),
        m(
            "coin_budget_exhausted_share",
            "coin_budget_exhausted share of attempts",
            stats.exhausted_share,
            "share",
        ),
        m("avg_notional_usd", "realised avg notional (N4)", stats.avg_notional_usd, "usd"),
        m("realized", "realized (arbitrage net)", stats.realized, "usd"),
        m("rebal_costs", "rebalance costs", stats.rebal_costs, "usd"),
        m("rebal_transfer", "  of which transfers", stats.rebal_transfer, "usd"),
        m("rebal_conversion", "  of which conversions", stats.rebal_conversion, "usd"),
        m("conversions_count", "conversions", stats.conversions_count, "int"),
        m("rebalances_blocked", "rebalances blocked", stats.rebalances_blocked, "int"),
        m("hedged", "hedged P&L (realized - rebal; reference only)", stats.hedged, "usd"),
        m("mtm", "MTM (price effect on inventory)", stats.mtm, "usd"),
        m("liq_cost", "liquidation reserve (exit cost, subtracted)", stats.liq_cost, "usd"),
        m("total", "total P&L (equity change)", stats.total, "usd"),
        m("total_liq", "total after liquidation reserve", stats.total_liq, "usd"),
        m("net_usd_per_month_pre_tax", "net $/month pre-tax", stats.net_usd_month(pre), "usd"),
        m(
            "net_usd_per_month_after_15",
            "net $/month after 15 % tax",
            stats.net_usd_month(t15),
            "usd",
        ),
        m(
            "net_usd_per_month_after_35",
            "net $/month after 35 % tax",
            stats.net_usd_month(t35),
            "usd",
        ),
        m("net_pct_per_month_pre_tax", "net %/month pre-tax", stats.net_pct_month(pre), "pct"),
        m(
            "net_pct_per_month_after_15",
            "net %/month after 15 % tax",
            stats.net_pct_month(t15),
            "pct",
        ),
        m(
            "net_pct_per_month_after_35",
            "net %/month after 35 % tax",
            stats.net_pct_month(t35),
            "pct",
        ),
        m("mtm_share", "MTM share |mtm| / (|realized-rebal| + |mtm|)", stats.mtm_share, "share"),
        m("mtm_dominated", "MTM-dominated (> 0.5)", stats.mtm_dominated, "flag"),
        m(
            "max_drawdown_pct",
            "max drawdown of daily equity, % of capital",
            stats.max_drawdown_pct,
            "pct",
        ),
        m("daily_pnl_std_pct", "daily P&L std, % of capital", stats.daily_pnl_std_pct, "pct"),
        m("cap_bound_sweeps_pct", "cap-bound sweeps %", stats.cap_bound_pct, "pct"),
        m("dropped_routes", "dropped routes (cap)", stats.dropped_routes, "int"),
        m("alerts_cap_excluded", "alerts cap-excluded (N1)", stats.alerts_cap_excluded, "int"),
        m(
            "unseeded_coin_value_usd",
            "unseeded coin value at window end (N10)",
            stats.unseeded_coin_value_usd,
            "usd",
        ),
        m("sweep_gap_hours", "hours without a sweep (N12)", stats.gap_hours, "int"),
        m("window_hours", "hours in window", stats.window_hours, "int"),
        m("gap_days", "days with gaps", ", ".join(stats.gap_days) or "none", "text"),
    ]


def jsonable(value: object) -> object:
    """Decimal -> string, tuples/lists/dicts recursively, dataclasses -> dicts (no raw rows)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        skip = {"data", "snapshots", "trades", "skips", "rebalances", "caps"}
        return {
            name: jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
            if name not in skip
        }
    return str(value)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_json(a: SetAnalysis, ops: OpsInputs | None) -> dict[str, object]:
    def block(stats: WindowStats | None) -> object:
        if stats is None:
            return None
        return {
            "from": _iso(stats.a_ms),
            "to": _iso(stats.b_ms),
            **{x.key: jsonable(x.value) for x in window_metrics(stats)},
        }

    run = a.data.run
    return {
        "set": a.name,
        "venues": list(run.venues),
        "run_id": run.run_id,
        "config_hash": run.config_hash,
        "since": _iso(run.started_ms),
        "window_start_used": _iso(a.start_ms),
        "previous_runs": [
            {"run_id": r.run_id, "started": _iso(r.started_ms), "config_hash": r.config_hash}
            for r in a.data.previous_runs
        ],
        "holdout_available": a.holdout is not None,
        "holdout_days_missing": jsonable(a.split.days_missing),
        "full_window": block(a.full),
        "tuning_in_sample": block(a.tuning),
        "holdout": block(a.holdout),
        "periods": [block(p.stats) for p in a.periods],
        "concentration_window": "holdout" if a.focus_is_holdout else "full (preview)",
        "concentration": {
            "top1_route_share": jsonable(a.concentration.top1_route_share),
            "top2_route_share": jsonable(a.concentration.top2_route_share),
            "top1_coin_share": jsonable(a.concentration.top1_coin_share),
            "top2_coin_share": jsonable(a.concentration.top2_coin_share),
            "hhi_routes": jsonable(a.concentration.hhi_routes),
            "top_routes": list(a.concentration.top_routes),
            "top_coins": list(a.concentration.top_coins),
            "net_pct_per_month_after_35_ex_top2_routes": jsonable(
                a.concentration.pct_ex_routes(GO_TAX_RATE)
            ),
            "net_pct_per_month_after_35_ex_top2_coins": jsonable(
                a.concentration.pct_ex_coins(GO_TAX_RATE)
            ),
            "unattributed_rebal_usd": jsonable(a.concentration.unattributed_rebal),
        },
        "ops": jsonable(ops) if ops is not None else None,
    }


def report_json(report: GoReport) -> dict[str, Any]:
    """JSON document with the same fields as the Markdown report (money as strings)."""
    verdict = report.verdict
    return {
        "version": REPORT_VERSION,
        "until": _iso(report.until_ms),
        "go_set": report.go_set,
        "tax_rates": [str(r) for r in TAX_RATES],
        "verdict_tax_rate": str(GO_TAX_RATE),
        "liq_cost_pct": str(report.liq_cost_pct),
        "gates": jsonable(report.gates),
        "verdict": jsonable(verdict) if verdict is not None else None,
        "sets": [_set_json(a, report.ops.get(a.name)) for a in report.analyses],
        "common_window": (
            {
                "from": _iso(report.common.start_ms),
                "to": _iso(report.common.until_ms),
                "basis": report.common.basis,
                "sets": {
                    name: {x.key: jsonable(x.value) for x in window_metrics(stats)}
                    for name, stats in report.common.rows
                },
            }
            if report.common is not None
            else None
        ),
        "fee_observations": jsonable(report.fees),
        "fee_source": "live exchange metadata, applied per trade; not part of the run hash",
    }
