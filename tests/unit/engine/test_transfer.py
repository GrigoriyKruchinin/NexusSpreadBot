from decimal import Decimal as D

from nexus.domain.models import AssetTransferInfo, NetworkInfo
from nexus.domain.spread import TransferStatus
from nexus.engine.transfer import select_transfer_route


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
