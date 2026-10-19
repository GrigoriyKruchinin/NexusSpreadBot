"""Binance public capital config (keyless transfer status)."""

from decimal import Decimal as D
from typing import Any

import ccxt
import httpx
import pytest

from nexus.adapters.cex.binance import BinanceAdapter
from nexus.adapters.cex.binance_public import BinancePublicTransferSource
from nexus.adapters.registry import AdapterOptions
from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import (
    ExchangeDataError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    ReadOnlyViolationError,
)
from nexus.domain.models import AssetTransferInfo
from nexus.interfaces.market_data import ITransferStatusSource
from tests.unit.adapters.fake_ccxt import FakeCcxtClient, load_fixture

_CODES = ccxt.binance()


def _source(handler: Any) -> BinancePublicTransferSource:
    return BinancePublicTransferSource(
        timeout_s=5,
        currency_code=_CODES.safe_currency_code,
        network_code=_CODES.network_id_to_code,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _ok(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET"
    return httpx.Response(200, json=load_fixture("binance", "public_capital_config"))


async def test_parses_flags_fees_contracts_and_unified_codes() -> None:
    source = _source(_ok)
    info = await source.load_transfer_info()
    await source.close()
    assert info is not None
    assert "UGX" not in info  # fiat skipped
    usdt = {n.network: n for n in info["USDT"].networks}
    assert set(usdt) == {"BEP20", "ERC20", "SOL", "TRC20"}  # ccxt codes, not Binance ids
    assert usdt["BEP20"].withdraw_fee == D("0.01")
    assert usdt["BEP20"].contract == "0x55d398326f99059ff775485246999027b3197955"
    zil = {n.network: n for n in info["ZIL"].networks}
    assert zil["ZIL"].withdraw_enabled is False
    assert zil["ZIL"].deposit_enabled is False
    assert zil["ZILEVM"].withdraw_enabled is True
    assert info["ONE"].networks[0].contract is None


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429), ExchangeRateLimitError),
        (httpx.Response(418), ExchangeRateLimitError),
        (httpx.Response(503), ExchangeUnavailableError),
        (httpx.Response(200, text="<html>"), ExchangeDataError),
        (httpx.Response(200, json={"success": False, "data": None}), ExchangeDataError),
        (httpx.Response(200, json={"success": True, "data": {}}), ExchangeDataError),
    ],
)
async def test_errors_are_translated(response: httpx.Response, error: type[Exception]) -> None:
    source = _source(lambda _: response)
    with pytest.raises(error):
        await source.load_transfer_info()


async def test_transport_errors_are_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(ExchangeUnavailableError, match="timed out"):
        await _source(boom).load_transfer_info()


async def test_client_is_get_only() -> None:
    source = _source(_ok)
    with pytest.raises(ReadOnlyViolationError):
        await source._client.post("https://www.binance.com/x")


async def test_network_codes_use_the_currency_code() -> None:
    body = {"success": True, "data": [{"coin": "ORDI", "networkList": [{"network": "BTC"}]}]}
    source = _source(lambda _: httpx.Response(200, json=body))
    info = await source.load_transfer_info()
    assert info is not None
    assert info["ORDI"].networks[0].network == _CODES.network_id_to_code("BTC", "ORDI")


async def test_malformed_entries_are_skipped() -> None:
    body = {
        "success": True,
        "data": [
            "junk",
            {"coin": 5},
            {"coin": "ABC", "networkList": ["x", {"network": None}, {"network": "ETH"}]},
        ],
    }
    source = _source(lambda _: httpx.Response(200, json=body))
    info = await source.load_transfer_info()
    assert info is not None
    abc = info["ABC"].networks
    assert [(n.network, n.withdraw_enabled, n.withdraw_fee) for n in abc] == [("ERC20", None, None)]


# ------------------------------------------------------------------ adapter fallback


class _Fallback(ITransferStatusSource):
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls, self.closed = result, error, 0, False

    async def load_transfer_info(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result

    async def close(self) -> None:
        self.closed = True


def _adapter(fallback: _Fallback, currencies: Any) -> BinanceAdapter:
    return BinanceAdapter(
        ExchangeCredentials(),
        AdapterOptions(),
        rest_client=FakeCcxtClient("binance", fetch_currencies=currencies),
        transfer_fallback=fallback,
    )


async def test_adapter_uses_fallback_only_without_ccxt_data() -> None:
    public = {"X": AssetTransferInfo(exchange="binance", asset="X")}
    fallback = _Fallback(result=public)
    adapter = _adapter(fallback, {})
    assert await adapter.load_transfer_info() == public
    primary = _adapter(fallback, load_fixture("gateio", "currencies"))
    assert "USDT" in (await primary.load_transfer_info() or {})
    assert fallback.calls == 1
    await adapter.close()
    assert fallback.closed


async def test_adapter_fallback_failure_degrades_to_unknown() -> None:
    fallback = _Fallback(error=ExchangeUnavailableError("binance", "down"))
    assert await _adapter(fallback, {}).load_transfer_info() is None


async def test_real_binance_adapter_wires_public_fallback() -> None:
    adapter = BinanceAdapter(ExchangeCredentials(), AdapterOptions())
    try:
        assert isinstance(adapter._transfer_fallback, BinancePublicTransferSource)
    finally:
        await adapter.close()
