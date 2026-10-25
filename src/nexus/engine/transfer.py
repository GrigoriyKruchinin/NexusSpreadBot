"""Transfer route selection between two venues (read-only metadata, no transfers are made)."""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Final

from nexus.domain.models import AssetTransferInfo, NetworkInfo
from nexus.domain.spread import LegState, TransferQuote, TransferStatus
from nexus.engine.network_times import estimated_arrival_min

NETWORK_ALIASES: Final[dict[str, str]] = {
    # Only synonyms of the SAME chain: each pair was observed on different exchanges with
    # identical token contracts (2026-10-19 metadata) or is the same chain in ccxt's network
    # maps, and never as two networks of one asset on one exchange (enforced by a table test
    # over tests/fixtures/networks/codes.json). ccxt unifies most codes already.
    # Chain migrations stay distinct (ZIL vs ZILEVM, SUI vs SUINEW, TON vs TON2): they are
    # different networks for deposits even when the ticker is the same.
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
    "AVAXCCHAIN": "AVAXC",  # Bitget
    "CAP20": "CHZ2",  # Chiliz Chain (Bitget)
    "RONIN": "RON",
    "KLAY": "KAIA",  # Klaytn rebranded to Kaia (same chain)
    "NEON3": "NEO3",
    "MERLBTC": "MERLIN",
    "STRKETH": "STARKNET",
    "XTZEVM": "ETHERLINK",
    "ZKSYNC2": "ZKSYNC",  # zkSync Era
    "ZKSYNCERA": "ZKSYNC",
    "CRC20": "CRO",  # Cronos
    "XPL": "PLASMA",
    "RSK": "RBTC",  # Rootstock
    "SOVRBTC": "RBTC",
    "BTRBTC": "BITLAYER",
}

PARTIAL_CONTRACT_MAX_LEN: Final = 12
"""Some venues publish only a contract suffix (OKX ``ctAddr``, e.g. ``72315c``)."""
_PARTIAL_CONTRACT_RE: Final = re.compile(r"(0x)?[0-9a-f]{4,12}")


def normalize_network(network: str) -> str:
    """Upper-case, strip separators and resolve known aliases."""
    code = network.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    return NETWORK_ALIASES.get(code, code)


def _contract_key(network: NetworkInfo) -> str | None:
    return network.contract.strip().lower() if network.contract else None


def _contracts_conflict(a: NetworkInfo, b: NetworkInfo) -> bool:
    ca, cb = _contract_key(a), _contract_key(b)
    if not (ca and cb) or ca == cb:
        return False
    short, full = sorted((ca, cb), key=len)
    if len(short) <= PARTIAL_CONTRACT_MAX_LEN < len(full):
        # A published hex suffix is compared as a suffix; placeholders ("0", "x") conflict.
        suffix = short.removeprefix("0x")
        return not (_PARTIAL_CONTRACT_RE.fullmatch(short) and full.endswith(suffix))
    return True


def _index_networks(info: AssetTransferInfo) -> tuple[dict[str, NetworkInfo], set[str]]:
    """Networks by normalized code, plus codes that two raw networks collapse into.

    An ambiguous code (e.g. an alias colliding with a distinct network of the same asset)
    is never treated as a usable route.
    """
    indexed: dict[str, NetworkInfo] = {}
    ambiguous: set[str] = set()
    for network in info.networks:
        code = normalize_network(network.network)
        if code in indexed:
            ambiguous.add(code)
        indexed[code] = network
    return indexed, ambiguous


def _leg_state(
    info: AssetTransferInfo | None,
    indexed: dict[str, NetworkInfo],
    network: str | None,
    *,
    withdraw: bool,
) -> LegState:
    """Withdraw (source) or deposit (destination) state; ``UNKNOWN`` unless reported."""
    if info is None:
        return LegState.UNKNOWN

    def flag_of(item: NetworkInfo) -> bool | None:
        return item.withdraw_enabled if withdraw else item.deposit_enabled

    asset_flag = info.withdraw_enabled if withdraw else info.deposit_enabled
    if asset_flag is False:
        return LegState.CLOSED
    if network is not None and network in indexed:
        flag = flag_of(indexed[network])
        if flag is None:
            return LegState.OPEN if asset_flag else LegState.UNKNOWN
        return LegState.OPEN if flag else LegState.CLOSED
    flags = [flag_of(item) for item in info.networks]
    if flags and all(flag is False for flag in flags):
        return LegState.CLOSED
    if any(flag is True for flag in flags):
        return LegState.OPEN
    return LegState.OPEN if asset_flag else LegState.UNKNOWN


def _with_details(
    quote: TransferQuote,
    source: AssetTransferInfo | None,
    destination: AssetTransferInfo | None,
) -> TransferQuote:
    """Attach withdraw/deposit states, minimums and approximate time to a route quote."""
    src = _index_networks(source)[0] if source is not None else {}
    dst = _index_networks(destination)[0] if destination is not None else {}
    code = quote.network
    out = src.get(code) if code else None
    into = dst.get(code) if code else None
    published = [
        value
        for value in (
            out.est_arrival_min if out else None,
            into.est_arrival_min if into else None,
        )
        if value is not None
    ]
    # Venue estimates can be too optimistic (Binance: 1 min for BTC), so the slower of the
    # venue estimate and the table wins; the label says which one it was.
    table = estimated_arrival_min(code)
    arrival: Decimal | None
    arrival_source: str | None
    if published and (table is None or max(published) >= table):
        arrival, arrival_source = max(published), "exchange"
    elif table is not None:
        arrival, arrival_source = table, "table"
    else:
        arrival, arrival_source = None, None
    busy_flags = [x.busy for x in (out, into) if x is not None and x.busy is not None]
    return replace(
        quote,
        withdraw_state=_leg_state(source, src, code, withdraw=True),
        deposit_state=_leg_state(destination, dst, code, withdraw=False),
        withdraw_min=out.withdraw_min if out else None,
        deposit_min=into.deposit_min if into else None,
        deposit_confirmations=into.deposit_confirmations if into else None,
        est_arrival_min=arrival,
        arrival_source=arrival_source,
        busy=any(busy_flags) if busy_flags else None,
    )


def select_transfer_route(
    source: AssetTransferInfo | None, destination: AssetTransferInfo | None
) -> TransferQuote:
    """Cheapest route (see :func:`_select_route`) with withdraw/deposit states and timing."""
    return _with_details(_select_route(source, destination), source, destination)


def _select_route(
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

    src, src_ambiguous = _index_networks(source)
    dst, dst_ambiguous = _index_networks(destination)

    if all(n.withdraw_enabled is False for n in source.networks):
        return TransferQuote(
            TransferStatus.UNAVAILABLE, note=f"withdrawals disabled on {source.exchange}"
        )
    if all(n.deposit_enabled is False for n in destination.networks):
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
        if code in src_ambiguous or code in dst_ambiguous:
            undetermined = True
            continue
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
    return TransferQuote(
        TransferStatus.VERIFIED,
        network=network,
        fee_base=fee,
        contract_verified=_contracts_match(src[network], dst[network]),
    )


def _contracts_match(a: NetworkInfo, b: NetworkInfo) -> bool:
    if not (a.contract and b.contract):
        return False
    return a.contract.strip().lower() == b.contract.strip().lower()
