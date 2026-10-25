"""HT1 S5: extended NetworkInfo fields, regression of the old ones, list_transfer_routes."""

import json
from collections.abc import Mapping
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from nexus.adapters.cex.binance_public import BinancePublicTransferSource
from nexus.domain.models import AssetTransferInfo, NetworkInfo
from nexus.engine.transfer import list_transfer_routes, select_transfer_route
from nexus.scanner.universe import MarketUniverse, UniverseFilter
from tests.unit.adapters.fake_ccxt import FakeCcxtClient, load_fixture
from tests.unit.adapters.test_ccxt_adapters import _adapter

SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures" / "networks" / "pre_s5_snapshot.json"


def snapshot_networks(info: Mapping[str, AssetTransferInfo] | None) -> dict[str, Any]:
    """Only the pre-S5 fields, as plain JSON."""
    assert info is not None
    return {
        asset: [
            asset_info.withdraw_enabled,
            asset_info.deposit_enabled,
            [
                [
                    n.network,
                    n.withdraw_enabled,
                    n.deposit_enabled,
                    None if n.withdraw_fee is None else str(n.withdraw_fee),
                    n.contract,
                ]
                for n in asset_info.networks
            ],
        ]
        for asset, asset_info in sorted(info.items())
    }


async def binance_public_info() -> Mapping[str, AssetTransferInfo] | None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("binance", "public_capital_config"))

    import ccxt

    codes = ccxt.binance()
    source = BinancePublicTransferSource(
        timeout_s=5,
        currency_code=codes.safe_currency_code,
        network_code=codes.network_id_to_code,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        return await source.load_transfer_info()
    finally:
        await source.close()


@pytest.mark.parametrize("exchange", ["kucoin", "mexc", "bitget", "gateio"])
async def test_pre_existing_fields_unchanged_on_fixtures(exchange: str) -> None:
    expected = json.loads(SNAPSHOT.read_text())[exchange]
    assert snapshot_networks(await _adapter(exchange).load_transfer_info()) == expected


async def test_pre_existing_fields_unchanged_binance_public() -> None:
    expected = json.loads(SNAPSHOT.read_text())["binance_public"]
    assert snapshot_networks(await binance_public_info()) == expected


async def test_binance_public_parses_new_fields() -> None:
    info = await binance_public_info()
    assert info is not None
    one = info["ONE"].networks[0]
    assert one.withdraw_min == D("60")
    assert one.busy is False
    assert one.deposit_min is None
    assert one.deposit_confirmations is None


async def test_binance_public_confirmations_dust_and_arrival() -> None:
    entry = {
        "network": "ETH",
        "withdrawEnable": True,
        "depositEnable": True,
        "withdrawFee": "1",
        "withdrawMin": "-1",
        "depositDust": "0.5",
        "minConfirm": 12,
        "estimatedArrivalTime": 3,
        "busy": True,
    }
    bad = {**entry, "network": "TRX", "minConfirm": "x", "estimatedArrivalTime": True}
    body = {"success": True, "data": [{"coin": "ABC", "networkList": [entry, bad]}]}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    source = BinancePublicTransferSource(
        timeout_s=5,
        currency_code=lambda c: c,
        network_code=lambda n, _c: n,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    info = await source.load_transfer_info()
    await source.close()
    assert info is not None
    good, broken = info["ABC"].networks
    assert good.withdraw_min is None  # negative is rejected
    assert good.deposit_min == D("0.5")
    assert good.deposit_confirmations == 12
    assert good.est_arrival_min == D(3)
    assert good.busy is True
    assert broken.deposit_confirmations is None
    assert broken.est_arrival_min is None


@pytest.mark.parametrize(
    ("exchange", "info_key", "confirm"),
    [("okx", "minDepArrivalConfirm", 3), ("kucoin", "confirms", "20")],
)
async def test_ccxt_parses_limits_and_confirmations(
    exchange: str, info_key: str, confirm: int | str
) -> None:
    entry = {
        "withdraw": True,
        "deposit": True,
        "fee": 1,
        "limits": {"withdraw": {"min": 2.5}, "deposit": {"min": 0.1}},
        "info": {info_key: confirm},
    }
    client = FakeCcxtClient(exchange, fetch_currencies={"USDT": {"networks": {"TRC20": entry}}})
    info = await _adapter(exchange, client).load_transfer_info()
    assert info is not None
    net = info["USDT"].networks[0]
    assert net.withdraw_min == D("2.5")
    assert net.deposit_min == D("0.1")
    assert net.deposit_confirmations == int(confirm)


async def test_ccxt_missing_or_invalid_extras_are_none() -> None:
    entry = {
        "withdraw": True,
        "deposit": True,
        "fee": 1,
        "limits": {"withdraw": {"min": -1}, "deposit": None},
        "info": {"confirms": True, "minConfirm": "abc", "minDepArrivalConfirm": 0},
    }
    client = FakeCcxtClient("okx", fetch_currencies={"USDT": {"networks": {"TRC20": entry}}})
    info = await _adapter("okx", client).load_transfer_info()
    assert info is not None
    net = info["USDT"].networks[0]
    assert (net.withdraw_min, net.deposit_min, net.deposit_confirmations) == (None, None, None)
    client2 = FakeCcxtClient("okx", fetch_currencies={"USDT": {"networks": {"X": {"info": 1}}}})
    info2 = await _adapter("okx", client2).load_transfer_info()
    assert info2 is not None
    assert info2["USDT"].networks[0].deposit_confirmations is None


# ------------------------------------------------------------------ list_transfer_routes


def _net(
    name: str,
    *,
    w: bool | None = True,
    d: bool | None = True,
    fee: str | None = "1",
    contract: str | None = None,
) -> NetworkInfo:
    return NetworkInfo(
        network=name,
        withdraw_enabled=w,
        deposit_enabled=d,
        withdraw_fee=D(fee) if fee else None,
        contract=contract,
    )


def _info(exchange: str, *networks: NetworkInfo, **kw: bool) -> AssetTransferInfo:
    return AssetTransferInfo(exchange=exchange, asset="ABC", networks=networks, **kw)


def test_list_routes_returns_every_verified_network_sorted_by_fee() -> None:
    src = _info("a", _net("ERC20", fee="5"), _net("trc20", fee="1"), _net("SOL", fee="1"))
    dst = _info("b", _net("ERC20"), _net("TRC20"), _net("SOL"), _net("BSC"))
    routes = list_transfer_routes(src, dst)
    assert [code for code, _, _ in routes] == ["SOL", "TRC20", "ERC20"]
    assert routes[0][1].withdraw_fee == D(1)
    # the cheapest-only selector is consistent with the head of the list
    assert select_transfer_route(src, dst).network == "SOL"


def test_list_routes_excludes_unverifiable_networks() -> None:
    src = _info(
        "a",
        _net("ERC20", w=False),
        _net("TRC20", fee=None),
        _net("SOL", w=None),
        _net("ARB", contract="0xaaaa" + "0" * 36),
        _net("OP"),
        _net("BEP20", d=True),
    )
    dst = _info(
        "b",
        _net("ERC20"),
        _net("TRC20"),
        _net("SOL"),
        _net("ARB", contract="0xbbbb" + "0" * 36),
        _net("OP", d=None),
        _net("BEP20", d=False),
    )
    assert list_transfer_routes(src, dst) == ()


def test_list_routes_ambiguous_code_and_asset_level_flags() -> None:
    src = _info("a", _net("ETH"), _net("ERC20"))  # both collapse to ERC20
    dst = _info("b", _net("ERC20"))
    assert list_transfer_routes(src, dst) == ()
    ok_src, ok_dst = _info("a", _net("ERC20")), _info("b", _net("ERC20"))
    assert len(list_transfer_routes(ok_src, ok_dst)) == 1
    assert list_transfer_routes(None, ok_dst) == ()
    assert list_transfer_routes(ok_src, None) == ()
    assert list_transfer_routes(_info("a", _net("ERC20"), withdraw_enabled=False), ok_dst) == ()
    assert list_transfer_routes(ok_src, _info("b", _net("ERC20"), deposit_enabled=False)) == ()


def test_universe_records_transfer_load_time() -> None:
    rules = UniverseFilter(quote_assets=frozenset({"USDT"}))
    universe = MarketUniverse.build({}, {}, rules, {"a": 1_000})
    assert universe.transfers_loaded_at_ms == {"a": 1_000}
    assert MarketUniverse.build({}, {}, rules).transfers_loaded_at_ms == {}
    assert universe.with_taker_fees({}).transfers_loaded_at_ms == {"a": 1_000}
