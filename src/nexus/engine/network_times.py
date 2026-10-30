"""Approximate transfer time per network (minutes), used alongside venue estimates.

Exchanges do not publish arrival times through the status API (only some report an estimate;
Binance's public estimate is unreliable for PoW chains, e.g. 1 min for BTC), so the route logic
takes ``max(exchange estimate, table value)``. The values below are rounded chain-level figures:
block time times the confirmations venues require to credit a deposit, plus a 1-2 min allowance
for withdrawal processing on fast chains. They are shown to the user as "approx"; congestion and
manual venue reviews can make real transfers slower.

Sources: Binance and KuCoin public currency metadata (credit confirmations, accessed
2026-10-25) plus chain block times. OKX, Bybit and Gate figures are NOT verified (they need a
read-only key or the logged-in deposit page); LINEA, CRO, KAIA and XMR rely on block time only.
Keys are codes after :func:`nexus.engine.transfer.normalize_network`..

TODO: model exchange withdrawal processing (typically 1-5 min, risk review 30 min to hours) as a
separate term instead of the allowance above; the report gives no measured default (no keys).
TODO: ``unlock_min`` (withdrawal unlock after credit) for capital rotation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

NETWORK_ARRIVAL_MIN: Final[dict[str, Decimal]] = {
    code: Decimal(minutes)
    for code, minutes in {
        # EVM chains and L2s (credit confs: Binance / KuCoin public metadata, 2026-10-25)
        "ERC20": 5,  # 12 s blocks, 6 (Binance) - 12 (KuCoin) confs; OKX up to 32-64
        "BEP20": 2,  # 0.45 s blocks since Fermi (2026-01), 1-15 confs
        "OPBNB": 5,  # Binance estimate 5 min
        "POLYGON": 8,  # ~2 s blocks, 200 confs (~7 min)
        "ARB": 3,  # ~0.25 s blocks, 120 confs
        "OP": 4,  # 2 s blocks, 25-100 confs
        "BASE": 4,  # 2 s blocks, 1-100 confs
        "AVAXC": 2,  # 12-32 confs
        "ZKSYNC": 5,  # Binance estimate 5 min; withdrawal unlock up to 24 h
        "LINEA": 5,  # unverified
        "MANTLE": 5,  # 2 s blocks, 100 confs (KuCoin)
        "SCROLL": 3,
        "STARKNET": 5,  # Binance estimate 3 min
        "MANTA": 3,
        "WORLDCHAIN": 4,
        "CELO": 8,  # Binance estimate 7 min
        "SONIC": 2,
        "SEIEVM": 2,
        "KAVAEVM": 3,
        "PLASMA": 2,
        "MONAD": 2,
        "RON": 12,  # Binance: 12 confs, estimate 12 min
        "KAIA": 2,
        "CRO": 2,  # unverified
        "KCC": 2,
        "XDC": 3,
        "CFX": 5,  # KuCoin 500 confs (~0.5 s)
        # fast non-EVM chains
        "TRC20": 2,  # 3 s blocks, 1-3 confs (OKX ~19)
        "SOL": 2,  # 0.4 s slots, 1-200 slots
        "XRP": 2,
        "XLM": 2,
        "TON": 2,  # ~0.4 s blocks since 2026-04
        "TON2": 2,  # KuCoin second TON chain, same chain time
        "NEAR": 2,
        "APT": 2,
        "SUI": 2,
        "SUINEW": 2,  # Gate, same chain time as SUI
        "ALGO": 2,
        "HBAR": 2,
        "EOS": 2,
        "AVAX": 2,  # Avalanche X-Chain (not AVAXC)
        "XTZ": 3,
        "ATOM": 3,  # ~6 s blocks, 10-15 confs
        "DOT": 4,  # relay chain
        "STATEMINT": 4,  # Polkadot Asset Hub, 3-30 confs
        "ADA": 12,  # ~20 s blocks, 30 confs
        # slow proof-of-work and legacy chains
        "BTC": 30,  # 10 min blocks, 1 conf to credit (2-3 to unlock) + mempool wait
        "SEGWITBTC": 30,
        "LIGHTNING": 1,
        "LTC": 25,  # 2.5 min blocks, 3 (Binance) - 12 (KuCoin) confs
        "DOGE": 15,  # 1 min blocks, 6-12 confs
        "BCH": 30,  # 10 min blocks, 2-3 confs
        "ETC": 45,  # ~13 s blocks, 70 (Binance) - 300 (KuCoin) confs
        "XMR": 25,  # 10-block spend lock, 3-15 confs
    }.items()
}


def estimated_arrival_min(network: str | None) -> Decimal | None:
    """Table estimate for a normalized network code; ``None`` when the network is not listed."""
    if network is None:
        return None
    return NETWORK_ARRIVAL_MIN.get(network)
