"""GO verdict logic (pure): stability, concentration gates, data-quality flags, ADR 0008 outcome.

Spec: ``docs/quant/b15-review-and-report-spec.md`` B5-B7; ADR 0008 (GO-HOLD).
The verdict is for ONE set (the GO set); other sets are context only (no best-of selection).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from nexus.reports.go_math import (
    GO_BAR_PCT,
    GO_TAX_RATE,
    TAX_RATES,
    ZERO,
    SetAnalysis,
    after_tax,
)

MAX_SINGLE_PERIOD_SHARE = Decimal("0.6")
MAX_EXHAUSTED_SHARE = Decimal("0.05")
MAX_TIMED_OUT_PCT = Decimal(2)
MAX_GAP_SHARE = Decimal("0.05")
MAX_CAP_BOUND_PCT = Decimal(20)

GO = "GO"
GO_HOLD = "GO-HOLD"
NOT_GO = "NOT GO (rework)"
NOT_GO_TAX = "NOT GO (rework; tax-rate sensitive, ask the accountant)"
INSUFFICIENT = "INSUFFICIENT DATA"
DATA_QUALITY = "NO VERDICT (data quality)"
NO_GO_LEGAL = "NO-GO (legal)"


@dataclass(frozen=True, slots=True)
class GateStatus:
    """Legal/access gates at report time (``docs/legal/go-gates-checklist.md``)."""

    open_gates: tuple[str, ...] = ()
    """Gates, keys or residence items not cleared yet (any entry = GO-HOLD instead of GO)."""
    legal_no_go: bool = False
    """A human lawyer says a gate cannot be cleared because of real legal penalties."""


@dataclass(frozen=True, slots=True)
class OpsInputs:
    """Operational facts that are not persisted in the database (supplied from logs/metrics)."""

    timed_out_pct: Decimal | None = None
    membership_missing: int | None = None
    regimes: tuple[str, ...] = ()
    """One label per stability period (e.g. BTC 30-day volatility bucket)."""


@dataclass(frozen=True, slots=True)
class Flag:
    """A data-quality or confidence flag."""

    code: str
    text: str
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class RateEvaluation:
    """Money, stability and concentration gates of the holdout at one tax rate."""

    rate: Decimal
    aggregate_pct: Decimal
    money_ok: bool
    period_pcts: tuple[Decimal, ...]
    periods_positive: bool
    periods_at_bar: int
    periods_at_bar_needed: int
    periods_at_bar_ok: bool
    max_period_share: Decimal
    share_ok: bool
    ex_routes_pct: Decimal
    ex_routes_ok: bool
    ex_coins_pct: Decimal
    ex_coins_ok: bool

    @property
    def stability_ok(self) -> bool:
        """All three stability conditions (B5)."""
        return self.periods_positive and self.periods_at_bar_ok and self.share_ok

    @property
    def concentration_ok(self) -> bool:
        """Both strict ex-top-2 tests (B6, user decision 2026-10-23)."""
        return self.ex_routes_ok and self.ex_coins_ok

    @property
    def passed(self) -> bool:
        """Money, stability and concentration all pass."""
        return self.money_ok and self.stability_ok and self.concentration_ok


def evaluate_rate(analysis: SetAnalysis, rate: Decimal) -> RateEvaluation | None:
    """Gate results at ``rate`` on the holdout; ``None`` while the holdout is insufficient."""
    holdout = analysis.holdout
    if holdout is None:
        return None
    k = len(analysis.periods)
    period_pcts = tuple(p.stats.net_pct_month(rate) for p in analysis.periods)
    at_bar = sum(1 for p in period_pcts if p >= GO_BAR_PCT)
    needed = math.ceil(k / 2)
    positives = [max(p.stats.total_liq, ZERO) for p in analysis.periods]
    positive_sum = sum(positives, ZERO)
    max_share = max(positives) / positive_sum if positive_sum > ZERO else Decimal(1)
    conc = analysis.concentration
    ex_routes = conc.pct_ex_routes(rate)
    ex_coins = conc.pct_ex_coins(rate)
    aggregate = holdout.net_pct_month(rate)
    return RateEvaluation(
        rate=rate,
        aggregate_pct=aggregate,
        money_ok=aggregate >= GO_BAR_PCT,
        period_pcts=period_pcts,
        periods_positive=all(p > ZERO for p in period_pcts),
        periods_at_bar=at_bar,
        periods_at_bar_needed=needed,
        periods_at_bar_ok=at_bar >= needed,
        max_period_share=max_share,
        share_ok=max_share <= MAX_SINGLE_PERIOD_SHARE,
        ex_routes_pct=ex_routes,
        ex_routes_ok=ex_routes >= GO_BAR_PCT,
        ex_coins_pct=ex_coins,
        ex_coins_ok=ex_coins >= GO_BAR_PCT,
    )


def quality_flags(analysis: SetAnalysis, ops: OpsInputs) -> list[Flag]:
    """Data-quality (blocking) and confidence flags, on the focus window (B7.4, B7.5)."""
    focus = analysis.focus
    flags: list[Flag] = []
    if focus.exhausted_share > MAX_EXHAUSTED_SHARE:
        flags.append(
            Flag(
                "coin_budget_exhausted",
                f"coin_budget_exhausted is {focus.exhausted_share * 100:.1f} % of attempts (> 5 %)",
                blocking=True,
            )
        )
    if ops.timed_out_pct is not None and ops.timed_out_pct > MAX_TIMED_OUT_PCT:
        flags.append(
            Flag(
                "timed_out", f"{ops.timed_out_pct} % of candidates timed out (> 2 %)", blocking=True
            )
        )
    if focus.gap_share > MAX_GAP_SHARE:
        flags.append(
            Flag(
                "heartbeat_gaps",
                f"{focus.gap_hours} of {focus.window_hours} hours without a sweep "
                f"({focus.gap_share * 100:.1f} % > 5 %)",
                blocking=True,
            )
        )
    if focus.mtm_dominated:
        flags.append(Flag("mtm_dominated", "result is MTM-dominated (|mtm| share > 50 %)"))
    cap = focus.cap_bound_pct
    if cap is not None and cap > MAX_CAP_BOUND_PCT:
        flags.append(Flag("cap_bound", f"candidate cap binds in {cap:.1f} % of sweeps (> 20 %)"))
    if len(set(ops.regimes)) < 2:
        flags.append(
            Flag("single_regime", "market regime of the periods unknown or a single regime")
        )
    if ops.timed_out_pct is None:
        flags.append(Flag("timed_out_unverified", "timed-out share not supplied (N2 unverified)"))
    return flags


def confidence(flags: list[Flag]) -> str:
    """``low`` with a single/unknown regime, ``medium`` with any other confidence flag."""
    codes = {f.code for f in flags}
    if "single_regime" in codes:
        return "low"
    return "medium" if codes & {"mtm_dominated", "cap_bound", "timed_out_unverified"} else "high"


@dataclass(frozen=True, slots=True)
class Verdict:
    """Outcome for the GO set (ADR 0008)."""

    set_name: str
    label: str
    reasons: tuple[str, ...]
    open_gates: tuple[str, ...]
    confidence: str
    flags: tuple[Flag, ...]
    at_35: RateEvaluation | None
    at_15: RateEvaluation | None
    refute: tuple[str, ...] = field(default=())
    """What would refute it: smallest period, ex-top-2 results, the 35 % line."""


def _failures(ev: RateEvaluation) -> list[str]:
    pct = f"{ev.rate * 100:.0f} %"
    out: list[str] = []
    if not ev.money_ok:
        out.append(f"holdout {ev.aggregate_pct:.2f} %/month after {pct} tax < {GO_BAR_PCT} %")
    if not ev.periods_positive:
        out.append(f"a stability period is not positive after {pct} tax")
    if not ev.periods_at_bar_ok:
        out.append(
            f"only {ev.periods_at_bar} periods >= {GO_BAR_PCT} % (need {ev.periods_at_bar_needed})"
        )
    if not ev.share_ok:
        out.append(
            f"one period gives {ev.max_period_share * 100:.0f} % of the positive net (> 60 %)"
        )
    if not ev.ex_routes_ok:
        out.append(f"ex-top-2 routes {ev.ex_routes_pct:.2f} % < {GO_BAR_PCT} % after {pct} tax")
    if not ev.ex_coins_ok:
        out.append(f"ex-top-2 coins {ev.ex_coins_pct:.2f} % < {GO_BAR_PCT} % after {pct} tax")
    return out


def _refute(analysis: SetAnalysis, at_35: RateEvaluation | None) -> tuple[str, ...]:
    """Always printed (B7.7): the numbers that would break the conclusion."""
    if at_35 is None:
        return ("holdout not available yet: nothing to refute or confirm",)
    lines = [
        f"35 % tax line: holdout {at_35.aggregate_pct:.2f} %/month (bar {GO_BAR_PCT} %)",
        f"smallest period: {min(at_35.period_pcts):.2f} %/month after 35 % tax",
        f"ex-top-2 routes: {at_35.ex_routes_pct:.2f} %/month; "
        f"ex-top-2 coins: {at_35.ex_coins_pct:.2f} %/month (after 35 % tax)",
    ]
    conc = analysis.concentration
    if conc.top_routes:
        lines.append(
            f"top-2 routes: {', '.join(conc.top_routes)}; top-2 coins: {', '.join(conc.top_coins)}"
        )
    return tuple(lines)


def decide(
    analysis: SetAnalysis, gates: GateStatus | None = None, ops: OpsInputs | None = None
) -> Verdict:
    """Verdict of the GO set: analytical GO -> GO / GO-HOLD, else rework / insufficient."""
    gates = gates or GateStatus()
    ops = ops or OpsInputs()
    flags = quality_flags(analysis, ops)
    at_35 = evaluate_rate(analysis, GO_TAX_RATE)
    at_15 = evaluate_rate(analysis, TAX_RATES[0])

    def verdict(label: str, *reasons: str) -> Verdict:
        return Verdict(
            set_name=analysis.name,
            label=label,
            reasons=reasons,
            open_gates=gates.open_gates,
            confidence=confidence(flags),
            flags=tuple(flags),
            at_35=at_35,
            at_15=at_15,
            refute=_refute(analysis, at_35),
        )

    if gates.legal_no_go:
        return verdict(
            NO_GO_LEGAL, "a lawyer reported real legal penalties: NO-GO regardless of the numbers"
        )
    if at_35 is None:
        return verdict(
            INSUFFICIENT,
            f"holdout shorter than 14 days or fewer than 2 periods: "
            f"{analysis.split.days_missing:.1f} more days of data needed "
            f"(window {analysis.split.total_days:.1f} d)",
        )
    blocking = [f.text for f in flags if f.blocking]
    if blocking:
        return verdict(DATA_QUALITY, *blocking)
    if at_35.passed:
        if gates.open_gates:
            return verdict(
                GO_HOLD,
                "analytical GO at 35 % tax; legal/access gates not cleared: "
                + ", ".join(gates.open_gates),
            )
        return verdict(GO, "all gates pass at 35 % tax and all legal/access gates are cleared")
    label = NOT_GO_TAX if at_15 is not None and at_15.passed else NOT_GO
    return verdict(label, *_failures(at_35))


__all__ = [
    "DATA_QUALITY",
    "GO",
    "GO_HOLD",
    "INSUFFICIENT",
    "NOT_GO",
    "NOT_GO_TAX",
    "NO_GO_LEGAL",
    "Flag",
    "GateStatus",
    "OpsInputs",
    "RateEvaluation",
    "Verdict",
    "after_tax",
    "confidence",
    "decide",
    "evaluate_rate",
    "quality_flags",
]
