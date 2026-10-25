"""Simulated A->B transfer duration (HT spec section 7). Pure, no I/O, nothing is ever moved.

``tau = tau_proc(A) + tau_conf(N, B) + 1 min credit``. The arrival is ONE reproducible draw seeded
from ``(run_hash, position_key)``; ``tau_p50`` / ``tau_p95`` are closed-form and drive pre-checks.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from nexus.engine.transfer import normalize_network

CREDIT_MIN: Final = Decimal(1)
"""Fixed credit/booking latency added to every transfer, minutes."""

UNKNOWN_CONF_MIN: Final = Decimal(60)
"""Median ``tau_conf`` when confirmations or block time are unknown (pessimistic)."""

CONF_P95_FACTOR: Final = Decimal("1.5")
"""``tau_conf`` p95 = median * this factor."""

PROC_SIGMA: Final = 0.7
"""Lognormal sigma of the withdrawal processing time on the source venue."""

Z95: Final = 1.6448536269514722
"""Standard normal 95th percentile."""

DEFAULT_P_STUCK: Final = 0.01
DEFAULT_STUCK_H: Final = 6

BLOCK_TIME_S: Final[dict[str, Decimal]] = {
    # Committed table, seconds per block (canonical codes of ``normalize_network``).
    "ERC20": Decimal(12),
    "BEP20": Decimal(3),
    "TRC20": Decimal(3),
    "SOL": Decimal("0.4"),
    "ARB": Decimal("0.25"),
    "OP": Decimal(2),
    "BASE": Decimal(2),
    "POLYGON": Decimal(2),
    "AVAXC": Decimal(2),
    "TON": Decimal(5),
    "APT": Decimal(1),
}

PROC_MEDIAN_MIN: Final[dict[str, Decimal]] = {
    # Median withdrawal processing minutes on the source venue.
    "binance": Decimal(3),
    "okx": Decimal(3),
    "kucoin": Decimal(5),
    "bybit": Decimal(3),
    "gateio": Decimal(10),
}
DEFAULT_PROC_MEDIAN_MIN: Final = Decimal(10)
"""Unlisted source venue: slowest listed median."""

_SECONDS_PER_MIN: Final = Decimal(60)


@dataclass(frozen=True, slots=True)
class TransitEstimate:
    """Closed-form quantiles plus the one reproducible draw (all minutes)."""

    tau_p50_min: Decimal
    tau_p95_min: Decimal
    tau_min: Decimal
    stuck: bool
    """True when the draw fell in the ``p_stuck`` tail (then ``tau_min = stuck_h * 60``)."""


def block_time_s(network: str) -> Decimal | None:
    """Seconds per block of ``network`` (any alias spelling); ``None`` when not in the table."""
    return BLOCK_TIME_S.get(normalize_network(network))


def conf_median_min(
    network: str,
    confirmations: int | None,
    dest_exchange: str,
    est_arrival_min: Decimal | None = None,
) -> Decimal:
    """Median confirmation wait on the destination, minutes.

    Unknown confirmations or block time -> 60 min. A Binance destination takes the larger of the
    block-based wait and the venue's own ``estimatedArrivalTime``.
    """
    block = block_time_s(network)
    if confirmations is None or confirmations <= 0 or block is None:
        base = UNKNOWN_CONF_MIN
    else:
        base = Decimal(confirmations) * block / _SECONDS_PER_MIN
    if dest_exchange == "binance" and est_arrival_min is not None and est_arrival_min > base:
        return est_arrival_min
    return base


def proc_median_min(source_exchange: str) -> Decimal:
    """Median processing minutes of a withdrawal on ``source_exchange``."""
    return PROC_MEDIAN_MIN.get(source_exchange, DEFAULT_PROC_MEDIAN_MIN)


def _proc_p95(median: Decimal) -> Decimal:
    return median * Decimal(repr(math.exp(PROC_SIGMA * Z95)))


def tau_quantiles(
    source_exchange: str,
    dest_exchange: str,
    network: str,
    confirmations: int | None,
    est_arrival_min: Decimal | None = None,
) -> tuple[Decimal, Decimal]:
    """``(tau_p50, tau_p95)`` in minutes (p95 = lognormal p95 + 1.5 * confirmation median)."""
    conf = conf_median_min(network, confirmations, dest_exchange, est_arrival_min)
    proc = proc_median_min(source_exchange)
    return proc + conf + CREDIT_MIN, _proc_p95(proc) + conf * CONF_P95_FACTOR + CREDIT_MIN


def seed_for(run_hash: str, position_key: str) -> int:
    """Stable integer seed: ``sha256(run_hash | position_key)``."""
    digest = hashlib.sha256(f"{run_hash}|{position_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def estimate_transit(
    *,
    run_hash: str,
    position_key: str,
    source_exchange: str,
    dest_exchange: str,
    network: str,
    confirmations: int | None,
    est_arrival_min: Decimal | None = None,
    p_stuck: float = DEFAULT_P_STUCK,
    stuck_h: int = DEFAULT_STUCK_H,
) -> TransitEstimate:
    """Quantiles and the seeded draw for one position (deterministic for a given seed)."""
    p50, p95 = tau_quantiles(
        source_exchange, dest_exchange, network, confirmations, est_arrival_min
    )
    rng = random.Random(seed_for(run_hash, position_key))  # noqa: S311 - simulation, not crypto
    stuck = rng.random() < p_stuck
    proc_draw = rng.lognormvariate(math.log(float(proc_median_min(source_exchange))), PROC_SIGMA)
    if stuck:
        tau = Decimal(stuck_h) * 60
    else:
        conf = conf_median_min(network, confirmations, dest_exchange, est_arrival_min)
        tau = Decimal(repr(round(proc_draw, 6))) + conf + CREDIT_MIN
    return TransitEstimate(tau_p50_min=p50, tau_p95_min=p95, tau_min=tau, stuck=stuck)
