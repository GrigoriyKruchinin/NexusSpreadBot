import json
import re
from decimal import Decimal as D
from pathlib import Path

import pytest

from nexus.domain.models import AssetTransferInfo, NetworkInfo
from nexus.domain.spread import LegState, TransferStatus
from nexus.engine.network_times import NETWORK_ARRIVAL_MIN, estimated_arrival_min
from nexus.engine.transfer import NETWORK_ALIASES, normalize_network, select_transfer_route


def _info(exchange: str, *networks: NetworkInfo) -> AssetTransferInfo:
    return AssetTransferInfo(exchange=exchange, asset="ABC", networks=networks)


def _net(name: str, *, w: bool = True, d: bool = True, fee: str | None = "1") -> NetworkInfo:
    return NetworkInfo(
        network=name, withdraw_enabled=w, deposit_enabled=d, withdraw_fee=D(fee) if fee else None
    )


def test_missing_metadata_is_unknown() -> None:
    assert select_transfer_route(None, _info("b", _net("ERC20"))).status is TransferStatus.UNKNOWN
    assert select_transfer_route(_info("a", _net("ERC20")), None).status is TransferStatus.UNKNOWN


def test_cheapest_common_network_selected() -> None:
    quote = select_transfer_route(
        _info("a", _net("ERC20", fee="5"), _net("trc20", fee="1"), _net("SOL", fee="0.1")),
        _info("b", _net("ERC20"), _net("TRC20")),
    )
    assert quote.status is TransferStatus.VERIFIED
    assert quote.network == "TRC20"
    assert quote.fee_base == D(1)


def test_withdrawals_disabled_everywhere_is_unavailable() -> None:
    quote = select_transfer_route(_info("a", _net("ERC20", w=False)), _info("b", _net("ERC20")))
    assert quote.status is TransferStatus.UNAVAILABLE
    assert "withdrawals disabled on a" in quote.note


def test_deposits_disabled_everywhere_is_unavailable() -> None:
    quote = select_transfer_route(_info("a", _net("ERC20")), _info("b", _net("ERC20", d=False)))
    assert quote.status is TransferStatus.UNAVAILABLE


def test_shared_networks_all_blocked_is_unavailable() -> None:
    # Same codes on both sides, but ERC20 withdrawals are off on the source and TRC20
    # deposits are off on the destination: positive evidence the asset cannot move.
    quote = select_transfer_route(
        _info("a", _net("ERC20", w=False), _net("TRC20")),
        _info("b", _net("ERC20"), _net("TRC20", d=False)),
    )
    assert quote.status is TransferStatus.UNAVAILABLE
    assert quote.note == "no common enabled network"


def test_disjoint_network_codes_are_unknown() -> None:
    quote = select_transfer_route(_info("a", _net("STATEMINT")), _info("b", _net("TON2")))
    assert quote.status is TransferStatus.UNKNOWN
    assert quote.note == "no common network code"


def test_aliases_are_resolved() -> None:
    quote = select_transfer_route(
        _info("a", _net("eth", fee="3"), _net("Tron", fee="1")),
        _info("b", _net("ERC20"), _net("TRC-20")),
    )
    assert quote.status is TransferStatus.VERIFIED
    assert quote.network == "TRC20"


def test_unreported_status_is_unknown_not_unavailable() -> None:
    unreported = NetworkInfo(
        network="ERC20", withdraw_enabled=None, deposit_enabled=None, withdraw_fee=D(1)
    )
    quote = select_transfer_route(_info("a", unreported), _info("b", _net("ERC20")))
    assert quote.status is TransferStatus.UNKNOWN
    assert quote.note == "network status not reported"


def test_contract_mismatch_blocks_route() -> None:
    src = NetworkInfo(
        network="ERC20",
        withdraw_enabled=True,
        deposit_enabled=True,
        withdraw_fee=D(1),
        contract="0xAAA",
    )
    dst = NetworkInfo(
        network="ERC20",
        withdraw_enabled=True,
        deposit_enabled=True,
        withdraw_fee=D(1),
        contract="0xbbb",
    )
    quote = select_transfer_route(_info("a", src), _info("b", dst))
    assert quote.status is TransferStatus.UNAVAILABLE


def test_contract_match_is_case_insensitive() -> None:
    src = NetworkInfo(
        network="ERC20",
        withdraw_enabled=True,
        deposit_enabled=True,
        withdraw_fee=D(1),
        contract="0xAbC",
    )
    dst = NetworkInfo(
        network="ERC20",
        withdraw_enabled=True,
        deposit_enabled=True,
        withdraw_fee=D(1),
        contract="0xabc",
    )
    assert select_transfer_route(_info("a", src), _info("b", dst)).status is TransferStatus.VERIFIED


def test_empty_network_list_is_unknown() -> None:
    assert select_transfer_route(_info("a"), _info("b", _net("ERC20"))).status is (
        TransferStatus.UNKNOWN
    )


def test_unknown_fee_is_unknown_not_zero() -> None:
    quote = select_transfer_route(_info("a", _net("ERC20", fee=None)), _info("b", _net("ERC20")))
    assert quote.status is TransferStatus.UNKNOWN
    assert quote.network == "ERC20"


def test_currency_level_disabled_without_network_list_is_unavailable() -> None:
    source = AssetTransferInfo(exchange="a", asset="ABC", networks=(), withdraw_enabled=False)
    quote = select_transfer_route(source, _info("b", _net("ERC20")))
    assert quote.status is TransferStatus.UNAVAILABLE
    destination = AssetTransferInfo(exchange="b", asset="ABC", networks=(), deposit_enabled=False)
    assert select_transfer_route(_info("a", _net("ERC20")), destination).status is (
        TransferStatus.UNAVAILABLE
    )


def test_contract_verified_only_when_both_match() -> None:
    def net(contract: str | None) -> NetworkInfo:
        return NetworkInfo(
            network="ERC20",
            withdraw_enabled=True,
            deposit_enabled=True,
            withdraw_fee=D(1),
            contract=contract,
        )

    def verified(a: str | None, b: str | None) -> bool:
        return select_transfer_route(_info("a", net(a)), _info("b", net(b))).contract_verified

    assert verified("0xAbC", "0xabc")
    assert not verified(None, "0xabc")
    assert not verified(None, None)


# ------------------------------------------------------------------ network matching

_CODES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "networks" / "codes.json").read_text()
)["exchanges"]
_LEGACY_ALIASES = {
    "ETH", "ETHEREUM", "TRX", "TRON", "BSC", "BNBSMARTCHAIN", "SOLANA", "ARBITRUM", "ARBONE",
    "ARBITRUMONE", "OPTIMISM", "MATIC",
}  # fmt: skip


def test_recorded_codes_never_collapse_within_one_asset() -> None:
    # An alias must never merge two distinct networks that one exchange lists for one asset.
    for exchange, assets in _CODES.items():
        for asset, codes in assets.items():
            normalized = [normalize_network(code) for code in codes]
            assert len(set(normalized)) == len(normalized), (exchange, asset, codes)


def test_every_new_alias_is_backed_by_recorded_codes() -> None:
    raw = {
        re.sub(r"[-_ ]", "", code.upper())
        for assets in _CODES.values()
        for codes in assets.values()
        for code in codes
    }
    recorded = {normalize_network(c) for c in raw}
    for alias, target in NETWORK_ALIASES.items():
        if alias in _LEGACY_ALIASES:
            continue
        assert alias in raw, f"alias {alias} not observed on any exchange"
        assert target in recorded, f"alias target {target} not observed on any exchange"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("ZIL", "ZILEVM"),
        ("ZIL", "zilliqa2"),
        ("SUI", "SUINEW"),
        ("TON", "TON2"),
        ("ERC20", "BEP20"),
    ],
)
def test_chain_migrations_stay_distinct(a: str, b: str) -> None:
    assert normalize_network(a) != normalize_network(b)
    quote = select_transfer_route(_info("x", _net(a)), _info("y", _net(b)))
    assert quote.status is TransferStatus.UNKNOWN


@pytest.mark.parametrize(
    ("bitget", "other"),
    [("AVAXCCHAIN", "AVAXC"), ("CAP20", "CHZ2"), ("RONIN", "RON"), ("KLAY", "KAIA")],
)
def test_proven_synonyms_match(bitget: str, other: str) -> None:
    quote = select_transfer_route(_info("bitget", _net(bitget)), _info("gateio", _net(other)))
    assert quote.status is TransferStatus.VERIFIED


def test_zil_native_suspended_and_zilevm_open_routes_over_zilevm_only() -> None:
    # The ZIL pattern: Binance native ZIL suspended, ZILEVM open; Gate lists only ZILEVM.
    binance = AssetTransferInfo(
        exchange="binance",
        asset="ZIL",
        networks=(_net("ZIL", w=False, d=False), _net("ZILEVM", fee="20")),
    )
    okx_native_only = AssetTransferInfo(exchange="okx", asset="ZIL", networks=(_net("ZIL"),))
    gate = AssetTransferInfo(exchange="gateio", asset="ZIL", networks=(_net("ZILEVM"),))
    assert select_transfer_route(binance, okx_native_only).status is TransferStatus.UNAVAILABLE
    quote = select_transfer_route(binance, gate)
    assert (quote.status, quote.network) == (TransferStatus.VERIFIED, "ZILEVM")


def test_colliding_codes_are_ambiguous_not_overwritten() -> None:
    # Two raw networks normalizing to one code: neither is trusted (no silent overwrite).
    source = _info("a", _net("ETH", w=False), _net("ERC20", fee="1"))
    quote = select_transfer_route(source, _info("b", _net("ERC20")))
    assert quote.status is TransferStatus.UNKNOWN


def _with_contract(name: str, contract: str) -> NetworkInfo:
    return NetworkInfo(name, True, True, D(1), contract=contract)


def test_partial_contract_suffix_is_compared_as_suffix() -> None:
    full = "0x64bc2ca1be492be7185faa2c8835d9b824c8a194"
    match = select_transfer_route(
        _info("okx", _with_contract("ERC20", "a194")), _info("b", _with_contract("ERC20", full))
    )
    assert match.status is TransferStatus.VERIFIED
    assert not match.contract_verified  # a suffix never lifts the unverified caps
    conflict = select_transfer_route(
        _info("okx", _with_contract("ERC20", "72315c")), _info("b", _with_contract("ERC20", full))
    )
    assert conflict.status is TransferStatus.UNAVAILABLE
    for placeholder in ("0", "x", "94", "zz194"):
        quote = select_transfer_route(
            _info("okx", _with_contract("ERC20", placeholder)),
            _info("b", _with_contract("ERC20", full)),
        )
        assert quote.status is TransferStatus.UNAVAILABLE, placeholder


# ---- withdraw / deposit states, minimums and approximate time (T3) -------------------


def test_open_route_reports_open_states_and_table_time() -> None:
    quote = select_transfer_route(_info("a", _net("TRC20")), _info("b", _net("TRC20")))
    assert quote.status is TransferStatus.VERIFIED
    assert (quote.withdraw_state, quote.deposit_state) == (LegState.OPEN, LegState.OPEN)
    assert quote.est_arrival_min == NETWORK_ARRIVAL_MIN["TRC20"]
    assert quote.arrival_source == "table"


def test_exchange_estimate_above_table_wins_and_takes_the_slower_side() -> None:
    src = NetworkInfo("ERC20", True, True, D(1), est_arrival_min=D(3), withdraw_min=D("0.5"))
    dst = NetworkInfo(
        "ETH",
        True,
        True,
        None,
        est_arrival_min=D(7),
        deposit_min=D("0.2"),
        deposit_confirmations=12,
        busy=True,
    )
    quote = select_transfer_route(_info("a", src), _info("b", dst))
    assert quote.network == "ERC20"
    assert (quote.est_arrival_min, quote.arrival_source) == (D(7), "exchange")
    assert (quote.withdraw_min, quote.deposit_min) == (D("0.5"), D("0.2"))
    assert quote.deposit_confirmations == 12
    assert quote.busy is True


def test_table_beats_too_optimistic_exchange_estimate() -> None:
    # Binance reports 1 min for BTC; the table (30) must win and be labelled "table".
    src = NetworkInfo("BTC", True, True, D(1), est_arrival_min=D(1))
    dst = NetworkInfo("BTC", True, True, None, est_arrival_min=D(1))
    quote = select_transfer_route(_info("a", src), _info("b", dst))
    assert (quote.est_arrival_min, quote.arrival_source) == (D(30), "table")


def test_exchange_estimate_equal_to_table_is_labelled_exchange() -> None:
    src = NetworkInfo("BTC", True, True, D(1), est_arrival_min=D(30))
    quote = select_transfer_route(_info("a", src), _info("b", _net("BTC")))
    assert (quote.est_arrival_min, quote.arrival_source) == (D(30), "exchange")


def test_exchange_estimate_on_unlisted_network_is_used() -> None:
    src = NetworkInfo("XYZNET", True, True, D(1), est_arrival_min=D(9))
    quote = select_transfer_route(_info("a", src), _info("b", _net("XYZNET")))
    assert (quote.est_arrival_min, quote.arrival_source) == (D(9), "exchange")


@pytest.mark.parametrize(
    ("code", "minutes"),
    [("POLYGON", 8), ("LTC", 25), ("ETC", 45), ("ADA", 12), ("SOL", 2), ("ZKSYNC", 5)],
)
def test_raised_slow_chains(code: str, minutes: int) -> None:
    assert NETWORK_ARRIVAL_MIN[code] == D(minutes)


@pytest.mark.parametrize(
    "code",
    ["STATEMINT", "TON2", "SUINEW", "OPBNB", "SONIC", "SEIEVM", "CELO", "KAVAEVM", "PLASMA",
     "SCROLL", "STARKNET", "MANTA", "RON", "XTZ", "XDC", "CFX", "KCC", "MONAD", "WORLDCHAIN",
     "AVAX", "LIGHTNING", "SEGWITBTC"],
)  # fmt: skip
def test_review_added_networks_have_own_rows(code: str) -> None:
    assert code in NETWORK_ARRIVAL_MIN
    assert normalize_network(code) == code


def test_unlisted_network_has_unknown_time() -> None:
    quote = select_transfer_route(_info("a", _net("XYZNET")), _info("b", _net("XYZNET")))
    assert quote.status is TransferStatus.VERIFIED
    assert quote.est_arrival_min is None
    assert quote.arrival_source is None
    assert quote.busy is None


def test_public_mode_venue_is_unknown_never_open() -> None:
    quote = select_transfer_route(None, None)
    assert quote.status is TransferStatus.UNKNOWN
    assert (quote.withdraw_state, quote.deposit_state) == (LegState.UNKNOWN, LegState.UNKNOWN)
    only_dest = select_transfer_route(None, _info("b", _net("TRC20")))
    assert only_dest.withdraw_state is LegState.UNKNOWN
    assert only_dest.deposit_state is LegState.OPEN  # no common network: any open one counts


def test_closed_deposit_and_withdraw_states() -> None:
    quote = select_transfer_route(_info("a", _net("TRC20")), _info("b", _net("TRC20", d=False)))
    assert quote.status is TransferStatus.UNAVAILABLE
    assert (quote.withdraw_state, quote.deposit_state) == (LegState.OPEN, LegState.CLOSED)
    closed_src = select_transfer_route(
        _info("a", _net("TRC20", w=False)), _info("b", _net("TRC20"))
    )
    assert closed_src.withdraw_state is LegState.CLOSED


def test_asset_level_flags_and_unreported_network_flags() -> None:
    src = AssetTransferInfo("a", "ABC", (_net("TRC20"),), withdraw_enabled=False)
    assert select_transfer_route(src, _info("b", _net("TRC20"))).withdraw_state is LegState.CLOSED
    unreported = NetworkInfo("TRC20", None, None, D(1))
    quote = select_transfer_route(_info("a", unreported), _info("b", unreported))
    assert quote.status is TransferStatus.UNKNOWN
    assert (quote.withdraw_state, quote.deposit_state) == (LegState.UNKNOWN, LegState.UNKNOWN)
    enabled = AssetTransferInfo("a", "ABC", (unreported,), withdraw_enabled=True)
    assert select_transfer_route(enabled, _info("b", unreported)).withdraw_state is LegState.OPEN


def test_network_table_keys_are_normalized_codes() -> None:
    for code in NETWORK_ARRIVAL_MIN:
        assert normalize_network(code) == code
        assert NETWORK_ARRIVAL_MIN[code] > 0
    assert estimated_arrival_min(None) is None
    assert estimated_arrival_min("NOPE") is None
