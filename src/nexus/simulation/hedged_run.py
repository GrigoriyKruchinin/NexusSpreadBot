"""HT1 run definition: settings -> :class:`HedgedConfig`, set specs and the pre-registered run hash.

The run hash covers every HT parameter of one set (spec section 13): the set id, spot and hedge
venues, the whole :class:`HedgedConfig` (including its code-only defaults), the extra settings
that do not live in that dataclass, and the code constants of the transit model. Changing any of
them is a different run (no silent in-sample tuning). It never includes the spot ``[paper]`` sets,
database or logging plumbing, so a host CLI and the container hash the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal

from nexus.config.groups import PaperHedgedSettings
from nexus.config.hedged_sets import parse_hedged_sets, parse_perp_fees
from nexus.simulation import transit
from nexus.simulation.hedged import HedgedConfig

HUNDRED = Decimal(100)
HASH_VERSION = 1
"""Bump when the hash payload layout changes."""


@dataclass(frozen=True, slots=True)
class HedgedSetSpec:
    """One HT set: its id and venues."""

    set_id: str
    spot_venues: tuple[str, ...]
    hedge_venues: tuple[str, ...]


def build_hedged_config(s: PaperHedgedSettings) -> HedgedConfig:
    """Map the settings (percent units) to the pure simulation config (fractions)."""
    return HedgedConfig(
        capital_usd=s.capital_usd,
        trade_notional_usd=s.trade_notional_usd,
        min_trade_usd=s.min_trade_usd,
        leverage=s.leverage,
        mmr_default=s.mmr_pct / HUNDRED,
        liq_min_distance=s.liq_min_distance_pct / HUNDRED,
        liq_sigma_k=s.liq_sigma_k,
        max_slippage=s.max_slippage_pct / HUNDRED,
        perp_taker_fee=parse_perp_fees(s.perp_taker_fee_pct),
        min_net_profit_pct=s.min_net_profit_pct,
        min_net_profit_usd=s.min_net_profit_usd,
        max_funding_cost=s.max_funding_cost_pct / HUNDRED,
        funding_negative_stress=s.funding_negative_stress,
        basis_z_max=s.basis_z_max,
        basis_std_floor=s.basis_std_floor,
        basis_min_samples=s.basis_min_samples,
        basis_pair_tolerance_ms=s.basis_pair_tolerance_s * 1000,
        kline_min_coverage=s.kline_min_coverage,
        unpriced_grace_h=s.unpriced_grace_h,
        leg_risk_reserve=s.leg_risk_reserve_pct / HUNDRED,
        max_open_positions=s.max_open_positions,
        route_cooldown_ms=s.route_cooldown_s * 1000,
        max_hold_h=s.max_hold_h,
        latency_ms=s.latency_ms,
        refill_threshold_usd=s.refill_threshold_usd,
        p_stuck=s.p_stuck,
        stuck_h=s.stuck_h,
    )


def hedged_set_specs(s: PaperHedgedSettings) -> list[HedgedSetSpec]:
    """The configured HT sets in order."""
    return [
        HedgedSetSpec(i, s.spot_venues, hedge) for i, hedge in parse_hedged_sets(s.sets).items()
    ]


def _norm(value: object) -> object:
    """Spelling-independent JSON form (``2`` and ``2.0`` hash alike)."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_norm(v) for v in value]
    if isinstance(value, float):
        return repr(value)
    return value


def hedged_run_hash(s: PaperHedgedSettings, spec: HedgedSetSpec) -> str:
    """SHA-256 over every HT parameter of ``spec`` (see module docstring)."""
    payload = {
        "v": HASH_VERSION,
        "set_id": spec.set_id,
        "spot_venues": sorted(spec.spot_venues),
        "hedge_venues": sorted(spec.hedge_venues),
        "hedge_policy": s.hedge_policy,
        "config": asdict(build_hedged_config(s)),
        "extra": {
            "basis_window_h": s.basis_window_h,
            "basis_spot_max_age_s": s.basis_spot_max_age_s,
            "max_open_per_coin": s.max_open_per_coin,
            "perp_ticker_interval_s": s.perp_ticker_interval_s,
            "funding_refresh_s": s.funding_refresh_s,
        },
        "transit": {
            "proc_median_min": transit.PROC_MEDIAN_MIN,
            "default_proc_median_min": transit.DEFAULT_PROC_MEDIAN_MIN,
            "proc_sigma": transit.PROC_SIGMA,
            "unknown_conf_min": transit.UNKNOWN_CONF_MIN,
            "conf_p95_factor": transit.CONF_P95_FACTOR,
            "block_time_s": transit.BLOCK_TIME_S,
        },
    }
    encoded = json.dumps(_norm(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
