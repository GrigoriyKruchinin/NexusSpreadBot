"""Approximate transfer time per network (minutes), used when the venue publishes no estimate.

Exchanges do not publish arrival times through the status API (only some report an estimate,
which then takes precedence). The values below are rough, rounded, chain-level figures:
typical block time multiplied by the confirmations venues usually require for a deposit,
plus a small allowance for withdrawal processing. They are intentionally coarse and shown to
the user as "approx"; congestion and manual venue reviews can make real transfers slower.

Sources: the block-time and confirmation figures that Binance, OKX, KuCoin and Bybit list on
their public deposit/withdrawal help pages (checked 2026-10), rounded up. Keys are codes after
:func:`nexus.engine.transfer.normalize_network`.

Status: values proposed by backend-lead (T3); crypto-specialist review pending
(see docs/tasks/tool/T3-alert-data-model.md).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

NETWORK_ARRIVAL_MIN: Final[dict[str, Decimal]] = {
    code: Decimal(minutes)
    for code, minutes in {
        # EVM chains and L2s
        "ERC20": 5,  # ~12 s blocks, 6-12 confirmations
        "BEP20": 2,  # ~3 s blocks, 15 confirmations
        "POLYGON": 5,  # ~2 s blocks, 64-128 confirmations
        "ARB": 3,
        "OP": 3,
        "BASE": 3,
        "AVAXC": 2,
        "ZKSYNC": 3,
        "LINEA": 5,
        "MANTLE": 3,
        "KAIA": 2,
        "CRO": 2,
        # fast non-EVM chains
        "TRC20": 2,  # ~3 s blocks, 19-20 confirmations
        "SOL": 1,
        "XRP": 2,
        "XLM": 2,
        "TON": 2,
        "NEAR": 2,
        "APT": 2,
        "SUI": 2,
        "ALGO": 2,
        "HBAR": 2,
        "EOS": 2,
        "ATOM": 4,
        "DOT": 4,
        "ADA": 10,
        # slow proof-of-work and legacy chains
        "BTC": 30,  # ~10 min blocks, 2-3 confirmations
        "LTC": 15,
        "DOGE": 15,
        "BCH": 30,
        "ETC": 30,
        "XMR": 25,
    }.items()
}


def estimated_arrival_min(network: str | None) -> Decimal | None:
    """Table estimate for a normalized network code; ``None`` when the network is not listed."""
    if network is None:
        return None
    return NETWORK_ARRIVAL_MIN.get(network)
