"""Transfer route selection between two venues (read-only metadata, no transfers are made)."""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from nexus.domain.models import AssetTransferInfo, NetworkInfo
from nexus.domain.spread import TransferQuote, TransferStatus

NETWORK_ALIASES: Final[dict[str, str]] = {
    # Only unambiguous synonyms of the same chain; ccxt unifies most codes already.
    "ETH": "ERC20",
    "ETHEREUM": "ERC20",
    "TRX": "TRC20",
    "TRON": "TRC20",
    "BSC": "BEP20",
    "BNBSMARTCHAIN": "BEP20",
    "SOLANA": "SOL",
    "ARBITRUM": "ARB",
    "ARBONE": "ARB",
    "ARBITRUMONE": "ARB",
    "OPTIMISM": "OP",
    "MATIC": "POLYGON",
}


def normalize_network(network: str) -> str:
    """Upper-case, strip separators and resolve known aliases."""
    code = network.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    return NETWORK_ALIASES.get(code, code)


def _contracts_conflict(a: NetworkInfo, b: NetworkInfo) -> bool:
    if not (a.contract and b.contract):
        return False
    return a.contract.strip().lower() != b.contract.strip().lower()


def select_transfer_route(
    source: AssetTransferInfo | None, destination: AssetTransferInfo | None
) -> TransferQuote:
    """Pick the cheapest network to move an asset from ``source`` to ``destination``.

    * ``VERIFIED`` - a common network is withdraw-enabled on the source, deposit-enabled on
      the destination, contracts do not conflict, and the withdrawal fee is known.
    * ``UNAVAILABLE`` - positive evidence that the asset cannot be moved: every shared
      network is disabled in the needed direction or has a different contract, or one side
      has every network disabled.
    * ``UNKNOWN`` - metadata missing, statuses/fees unreported, or network codes do not
      overlap at all (possible naming mismatch between exchanges).
    """
    if source is None or destination is None:
        missing = "source" if source is None else "destination"
        return TransferQuote(TransferStatus.UNKNOWN, note=f"no {missing} transfer metadata")
    if source.withdraw_enabled is False:
        return TransferQuote(
            TransferStatus.UNAVAILABLE, note=f"withdrawals disabled on {source.exchange}"
        )
    if destination.deposit_enabled is False:
        return TransferQuote(
            TransferStatus.UNAVAILABLE, note=f"deposits disabled on {destination.exchange}"
        )
    if not source.networks or not destination.networks:
        return TransferQuote(TransferStatus.UNKNOWN, note="network list not published")

    src = {normalize_network(n.network): n for n in source.networks}
    dst = {normalize_network(n.network): n for n in destination.networks}

    if all(n.withdraw_enabled is False for n in src.values()):
        return TransferQuote(
            TransferStatus.UNAVAILABLE, note=f"withdrawals disabled on {source.exchange}"
        )
    if all(n.deposit_enabled is False for n in dst.values()):
        return TransferQuote(
            TransferStatus.UNAVAILABLE, note=f"deposits disabled on {destination.exchange}"
        )

    shared = sorted(set(src) & set(dst))
    if not shared:
        return TransferQuote(TransferStatus.UNKNOWN, note="no common network code")

    open_routes: list[str] = []
    undetermined = False
    for code in shared:
        out, into = src[code], dst[code]
        if out.withdraw_enabled is False or into.deposit_enabled is False:
            continue
        if _contracts_conflict(out, into):
            continue
        if out.withdraw_enabled is None or into.deposit_enabled is None:
            undetermined = True
            continue
        open_routes.append(code)

    if not open_routes:
        if undetermined:
            return TransferQuote(TransferStatus.UNKNOWN, note="network status not reported")
        return TransferQuote(TransferStatus.UNAVAILABLE, note="no common enabled network")

    priced: list[tuple[Decimal, str]] = [
        (fee, code) for code in open_routes if (fee := src[code].withdraw_fee) is not None
    ]
    if not priced:
        return TransferQuote(
            TransferStatus.UNKNOWN, network=open_routes[0], note="withdrawal fee unknown"
        )
    fee, network = min(priced)
    return TransferQuote(TransferStatus.VERIFIED, network=network, fee_base=fee)
