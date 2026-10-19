from decimal import Decimal as D
from typing import Any

import ccxt
import pytest
from pydantic import SecretStr

from nexus.adapters.cex.binance import BinanceAdapter
from nexus.adapters.cex.bitget import BitgetAdapter
from nexus.adapters.cex.bybit import BybitAdapter
from nexus.adapters.cex.ccxt_base import CcxtExchangeAdapter, to_decimal
from nexus.adapters.cex.gateio import GateIoAdapter
from nexus.adapters.cex.kucoin import KucoinAdapter
from nexus.adapters.cex.mexc import MexcAdapter
from nexus.adapters.cex.okx import OkxAdapter
from nexus.adapters.registry import AdapterOptions, exchange_registry
from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import (
    ConfigurationError,
    ExchangeAuthError,
    ExchangeDataError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
)
from tests.unit.adapters.fake_ccxt import FakeCcxtClient

EXCHANGES = ("binance", "bitget", "bybit", "gateio", "kucoin", "mexc", "okx")
NOW = 1_800_000_000_000


class _Clock:
    def now_ms(self) -> int:
        return NOW


def _creds(
    api_key: str | None = None, api_secret: str | None = None, api_passphrase: str | None = None
) -> ExchangeCredentials:
    def wrap(value: str | None) -> SecretStr | None:
        return SecretStr(value) if value is not None else None

    return ExchangeCredentials(
        api_key=wrap(api_key), api_secret=wrap(api_secret), api_passphrase=wrap(api_passphrase)
    )


ADAPTERS: dict[str, type[CcxtExchangeAdapter]] = {
    "binance": BinanceAdapter,
    "bitget": BitgetAdapter,
    "bybit": BybitAdapter,
    "gateio": GateIoAdapter,
    "kucoin": KucoinAdapter,
    "mexc": MexcAdapter,
    "okx": OkxAdapter,
}


def _adapter(
    exchange: str,
    client: FakeCcxtClient | None = None,
    credentials: ExchangeCredentials | None = None,
    **options: Any,
) -> CcxtExchangeAdapter:
    adapter = ADAPTERS[exchange](
        credentials or ExchangeCredentials(),
        AdapterOptions(**options),
        clock=_Clock(),
        rest_client=client or FakeCcxtClient(exchange),
    )
    adapter.retry_backoff_s = 0  # type: ignore[misc]
    return adapter


def test_all_exchanges_registered() -> None:
    assert set(EXCHANGES) <= set(exchange_registry.names())
    assert set(ADAPTERS) == set(EXCHANGES)


@pytest.mark.parametrize("exchange", EXCHANGES)
async def test_registry_builds_real_clients_without_network(exchange: str) -> None:
    adapter = exchange_registry.create(exchange, ExchangeCredentials(), AdapterOptions())
    await adapter.close()


@pytest.mark.parametrize("exchange", EXCHANGES)
async def test_load_markets_spot_only_and_decimal(exchange: str) -> None:
    markets = {m.symbol: m for m in await _adapter(exchange).load_markets()}
    assert "BTC/USDT" in markets
    assert all(":" not in symbol for symbol in markets)  # swap/futures excluded
    btc = markets["BTC/USDT"]
    assert btc.exchange == exchange
    assert (btc.base, btc.quote) == ("BTC", "USDT")
    assert isinstance(btc.taker_fee, D)
    assert D(0) < btc.taker_fee < D("0.01")
    assert btc.amount_step is not None
    assert btc.amount_step > 0
    assert btc.active


@pytest.mark.parametrize("exchange", EXCHANGES)
async def test_fetch_tickers(exchange: str) -> None:
    tickers = await _adapter(exchange).fetch_tickers(["BTC/USDT"])
    assert set(tickers) == {"BTC/USDT"}
    ticker = tickers["BTC/USDT"]
    assert ticker.bid is not None
    assert ticker.ask is not None
    assert ticker.bid < ticker.ask
    assert ticker.quote_volume_24h is not None
    assert ticker.quote_volume_24h > 0
    assert ticker.timestamp_ms is None or ticker.timestamp_ms > 0


@pytest.mark.parametrize("exchange", EXCHANGES)
async def test_fetch_order_book(exchange: str) -> None:
    book = await _adapter(exchange).fetch_order_book("BTC/USDT", depth=5)
    assert book.exchange == exchange
    assert len(book.bids) == 5
    assert len(book.asks) == 5
    assert book.best_bid is not None
    assert book.best_ask is not None
    assert book.best_bid < book.best_ask
    assert book.received_at_ms == NOW


async def test_missing_book_timestamp_uses_receive_time() -> None:
    client = FakeCcxtClient(
        "bybit", fetch_order_book={"bids": [[1, 1]], "asks": [[2, 1]], "timestamp": None}
    )
    book = await _adapter("bybit", client).fetch_order_book("BTC/USDT", 5)
    assert book.timestamp_ms == NOW


async def test_order_book_drops_invalid_levels_and_rejects_crossed() -> None:
    client = FakeCcxtClient(
        "kucoin",
        fetch_order_book={
            "bids": [[100, 0, 0], [99, 1, 0]],
            "asks": [[101, 2, 0]],
            "timestamp": NOW,
        },
    )
    book = await _adapter("kucoin", client).fetch_order_book("BTC/USDT", 5)
    assert book.best_bid == D(99)
    client.payloads["fetch_order_book"] = {"bids": [[102, 1]], "asks": [[101, 1]], "timestamp": 1}
    with pytest.raises(ExchangeDataError, match="crossed"):
        await _adapter("kucoin", client).fetch_order_book("BTC/USDT", 5)


@pytest.mark.parametrize(
    ("exchange", "depth", "expected"),
    [
        ("binance", 30, 50),
        ("binance", 5000, 1000),
        ("kucoin", 5, 20),
        ("kucoin", 50, 100),
        ("bybit", 50, 50),
        ("bybit", 500, 200),
        ("gateio", 500, 100),
        ("mexc", 50, 50),
        ("mexc", 5000, 1000),
        ("bitget", 50, 50),
        ("bitget", 500, 150),
    ],
)
def test_order_book_limit(exchange: str, depth: int, expected: int) -> None:
    assert _adapter(exchange).order_book_limit(depth) == expected


def test_bybit_websocket_limits_differ_from_rest() -> None:
    adapter = _adapter("bybit")
    assert adapter.order_book_limit(20) == 20
    assert adapter.order_book_limit(20, websocket=True) == 50


def test_okx_websocket_uses_public_channels() -> None:
    # books50-l2-tbt requires a VIP4+ login: depth 50 must map to the public "books" channel.
    assert _adapter("okx").order_book_limit(50, websocket=True) == 400


@pytest.mark.parametrize(("depth", "expected"), [(5, 5), (10, 15), (50, 150)])
def test_bitget_websocket_uses_fixed_channels_or_full_feed(depth: int, expected: int) -> None:
    assert _adapter("bitget").order_book_limit(depth, websocket=True) == expected


async def test_watch_order_book_uses_ws_client() -> None:
    ws = FakeCcxtClient("bybit")
    adapter = BybitAdapter(
        ExchangeCredentials(),
        AdapterOptions(),
        clock=_Clock(),
        rest_client=FakeCcxtClient("bybit"),
        ws_client=ws,
    )
    book = await adapter.watch_order_book("BTC/USDT", 5)
    assert len(book.bids) == 5
    assert ws.calls == [("fetch_order_book", ("BTC/USDT", 50))]


async def test_unwatch_order_book_best_effort() -> None:
    ws = FakeCcxtClient("bybit", has={"unWatchOrderBook": True})
    adapter = BybitAdapter(
        ExchangeCredentials(),
        AdapterOptions(),
        clock=_Clock(),
        rest_client=FakeCcxtClient("bybit"),
        ws_client=ws,
    )
    await adapter.unwatch_order_book("BTC/USDT")
    ws.fail("un_watch_order_book", ccxt.NetworkError("gone"))
    await adapter.unwatch_order_book("BTC/USDT")  # errors are swallowed
    assert ws.calls == [("un_watch_order_book", ("BTC/USDT",))] * 2
    ws.has["unWatchOrderBook"] = False
    await adapter.unwatch_order_book("BTC/USDT")
    assert len(ws.calls) == 2


async def test_unwatch_without_ws_client_is_noop() -> None:
    await _adapter("bybit").unwatch_order_book("BTC/USDT")


async def test_kucoin_currencies_parsed() -> None:
    info = await _adapter("kucoin").load_transfer_info()
    assert info is not None
    usdt = info["USDT"]
    assert usdt.networks
    op = next(n for n in usdt.networks if n.network == "OP")
    assert op.withdraw_enabled is True
    assert op.deposit_enabled is False
    assert op.withdraw_fee == D(1)


@pytest.mark.parametrize(
    ("exchange", "network", "withdraw", "deposit", "fee", "contract"),
    [
        ("mexc", "TRC20", True, True, D(1), "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
        ("mexc", "BEP20", True, False, D(0), "0x55d398326f99059fF775485246999027B3197955"),
        ("bitget", "TRC20", True, True, D("1.5"), "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
    ],
)
async def test_new_exchange_currencies_parsed(
    exchange: str,
    network: str,
    withdraw: bool,
    deposit: bool,
    fee: D,
    contract: str,
) -> None:
    info = await _adapter(exchange).load_transfer_info()
    assert info is not None
    net = next(n for n in info["USDT"].networks if n.network == network)
    assert (net.withdraw_enabled, net.deposit_enabled) == (withdraw, deposit)
    assert net.withdraw_fee == fee
    assert net.contract == contract


async def test_bitget_extra_percentage_withdraw_fee_makes_fee_unknown() -> None:
    client = FakeCcxtClient("bitget", has={"fetchDepositWithdrawFees": True})
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    info = await _adapter("bitget", client, creds).load_transfer_info()
    assert info is not None
    burn = info["BURN"].networks[0]
    assert burn.withdraw_enabled is True
    assert burn.withdraw_fee is None  # 1 token + 10 % cannot be priced as a flat fee
    assert all(call[0] != "fetch_deposit_withdraw_fees" for call in client.calls)


@pytest.mark.parametrize(
    ("network", "expected"),
    [
        ({"fee": 0.8, "info": {"maxFee": "1.6"}}, D("0.8")),
        ({"fee": None, "info": {"minFee": "0.8", "maxFee": "1.6"}}, D("1.6")),
        ({"fee": None, "info": {}}, None),
    ],
)
async def test_okx_fee_falls_back_to_max_fee(network: dict[str, Any], expected: D | None) -> None:
    entry = {"withdraw": True, "deposit": True, **network}
    client = FakeCcxtClient("okx", fetch_currencies={"USDT": {"networks": {"TRC20": entry}}})
    info = await _adapter("okx", client).load_transfer_info()
    assert info is not None
    assert info["USDT"].networks[0].withdraw_fee == expected


async def test_mexc_btc_withdraw_suspended_and_empty_contract_ignored() -> None:
    info = await _adapter("mexc").load_transfer_info()
    assert info is not None
    btc = info["BTC"].networks[0]
    assert btc.withdraw_enabled is False
    assert btc.contract is None


@pytest.mark.parametrize("exchange", ["binance", "bybit", "okx", "mexc"])
async def test_currencies_without_credentials_are_none(exchange: str) -> None:
    # ccxt returns an empty mapping when the currency endpoint needs a key (e.g. MEXC).
    client = FakeCcxtClient(exchange, fetch_currencies={})
    assert await _adapter(exchange, client).load_transfer_info() is None


async def test_currency_level_disable_overrides_unknown_network_flags() -> None:
    client = FakeCcxtClient(
        "gateio",
        fetch_currencies={
            "XYZ": {
                "withdraw": False,
                "deposit": None,
                "networks": {"ERC20": {"withdraw": None, "deposit": None, "fee": None}},
            }
        },
    )
    info = await _adapter("gateio", client).load_transfer_info()
    assert info is not None
    net = info["XYZ"].networks[0]
    assert net.withdraw_enabled is False
    assert net.deposit_enabled is None


async def test_withdraw_fee_overrides_with_credentials() -> None:
    client = FakeCcxtClient(
        "gateio",
        has={"fetchDepositWithdrawFees": True},
        fetch_currencies={
            "XYZ": {"networks": {"ERC20": {"withdraw": True, "deposit": True, "fee": None}}}
        },
        fetch_deposit_withdraw_fees={"XYZ": {"networks": {"ERC20": {"withdraw": {"fee": 2.5}}}}},
    )
    info = await _adapter(
        "gateio", client, _creds(api_key="k", api_secret="s")
    ).load_transfer_info()
    assert info is not None
    assert info["XYZ"].networks[0].withdraw_fee == D("2.5")


async def test_fallback_fee_when_unreported() -> None:
    markets = {
        "A/USDT": {
            "symbol": "A/USDT",
            "base": "A",
            "quote": "USDT",
            "spot": True,
            "active": True,
            "taker": None,
            "precision": {},
            "limits": {},
        },
        "B/USDT": {
            "symbol": "B/USDT",
            "base": "B",
            "quote": "USDT",
            "spot": True,
            "active": True,
            "taker": 0,
            "precision": {},
            "limits": {},
        },
    }
    adapter = _adapter(
        "bybit", FakeCcxtClient("bybit", load_markets=markets), fallback_taker_fee=D("0.003")
    )
    result = {m.symbol: m for m in await adapter.load_markets()}
    assert result["A/USDT"].taker_fee == D("0.003")
    assert result["A/USDT"].taker_fee_is_default
    assert result["B/USDT"].taker_fee == D("0.003")


async def test_implausible_market_skipped() -> None:
    markets = {
        "A/USDT": {
            "symbol": "A/USDT",
            "base": "A",
            "quote": "USDT",
            "spot": True,
            "taker": 0.5,
            "precision": {},
            "limits": {},
        }
    }
    adapter = _adapter("bybit", FakeCcxtClient("bybit", load_markets=markets))
    assert await adapter.load_markets() == []


async def test_account_fees_override_with_credentials() -> None:
    client = FakeCcxtClient(
        "binance",
        has={"fetchTradingFees": True},
        fetch_trading_fees={"BTC/USDT": {"taker": 0.00075}},
    )
    adapter = _adapter("binance", client, _creds(api_key="k", api_secret="s"))
    btc = next(m for m in await adapter.load_markets() if m.symbol == "BTC/USDT")
    assert btc.taker_fee == D("0.00075")
    assert not btc.taker_fee_is_default


async def test_account_fee_failure_falls_back_to_public() -> None:
    client = FakeCcxtClient("binance", has={"fetchTradingFees": True})
    client.fail("fetch_trading_fees", ccxt.AuthenticationError("bad key"))
    adapter = _adapter("binance", client, _creds(api_key="k", api_secret="s"))
    btc = next(m for m in await adapter.load_markets() if m.symbol == "BTC/USDT")
    assert btc.taker_fee == D("0.001")


async def test_bitget_skips_public_bulk_fees() -> None:
    client = FakeCcxtClient(
        "bitget",
        has={"fetchTradingFees": True},
        fetch_trading_fees={"BTC/USDT": {"taker": 0.002}},
    )
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    btc = next(m for m in await _adapter("bitget", client, creds).load_markets())
    assert btc.taker_fee_is_default
    assert all(call[0] != "fetch_trading_fees" for call in client.calls)


@pytest.mark.parametrize("exchange", ["okx", "kucoin", "mexc", "bitget"])
async def test_per_symbol_taker_fee_with_credentials(exchange: str) -> None:
    client = FakeCcxtClient(
        exchange,
        has={"fetchTradingFee": True},
        fetch_trading_fee={"symbol": "BTC/USDT", "maker": 0.0008, "taker": 0.0009},
    )
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    adapter = _adapter(exchange, client, creds)
    assert await adapter.fetch_taker_fee("BTC/USDT") == D("0.0009")
    assert ("fetch_trading_fee", ("BTC/USDT",)) in client.calls


async def test_per_symbol_taker_fee_needs_credentials_and_sane_value() -> None:
    client = FakeCcxtClient("okx", has={"fetchTradingFee": True})
    assert await _adapter("okx", client).fetch_taker_fee("BTC/USDT") is None
    assert client.calls == []
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    for taker in (0.2, -0.001, None):
        client = FakeCcxtClient(
            "okx", has={"fetchTradingFee": True}, fetch_trading_fee={"taker": taker}
        )
        assert await _adapter("okx", client, creds).fetch_taker_fee("BTC/USDT") is None


async def test_per_symbol_taker_fee_rejects_other_symbol() -> None:
    client = FakeCcxtClient(
        "okx",
        has={"fetchTradingFee": True},
        fetch_trading_fee={"symbol": "ETH/USDT", "taker": 0.0009},
    )
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    assert await _adapter("okx", client, creds).fetch_taker_fee("BTC/USDT") is None


@pytest.mark.parametrize(
    ("info", "expected"),
    [({"takerUSDC": "-0.0015"}, D("0.0015")), ({"takerUSDC": "-0.0005"}, D("0.001")), ({}, None)],
)
async def test_okx_non_usdt_pair_uses_conservative_rate(
    info: dict[str, str], expected: D | None
) -> None:
    client = FakeCcxtClient(
        "okx",
        has={"fetchTradingFee": True},
        fetch_trading_fee={"symbol": "BTC/USDC", "taker": 0.001, "info": info},
    )
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    assert await _adapter("okx", client, creds).fetch_taker_fee("BTC/USDC") == expected


async def test_per_symbol_taker_fee_errors_are_translated() -> None:
    client = FakeCcxtClient("okx", has={"fetchTradingFee": True})
    client.fail("fetch_trading_fee", ccxt.RateLimitExceeded("slow down"))
    creds = _creds(api_key="k", api_secret="s", api_passphrase="p")
    with pytest.raises(ExchangeRateLimitError):
        await _adapter("okx", client, creds).fetch_taker_fee("BTC/USDT")


# ------------------------------------------------------------------ errors & retries


async def test_rate_limit_is_not_retried() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_tickers", ccxt.RateLimitExceeded("slow down"))
    with pytest.raises(ExchangeRateLimitError):
        await _adapter("okx", client).fetch_tickers(["BTC/USDT"])
    assert len([c for c in client.calls if c[0] == "fetch_tickers"]) == 1


async def test_transient_network_error_is_retried() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_tickers", ccxt.ExchangeNotAvailable("502"))
    assert "BTC/USDT" in await _adapter("okx", client).fetch_tickers(["BTC/USDT"])


async def test_network_errors_exhaust_retries() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_tickers", *(ccxt.RequestTimeout("t") for _ in range(3)))
    with pytest.raises(ExchangeUnavailableError):
        await _adapter("okx", client).fetch_tickers([])
    assert len(client.calls) == 3


async def test_auth_errors_not_retried() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_tickers", ccxt.AuthenticationError("invalid key"))
    with pytest.raises(ExchangeAuthError):
        await _adapter("okx", client).fetch_tickers([])
    assert len(client.calls) == 1


async def test_ddos_protection_maps_to_rate_limit_error() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_tickers", ccxt.DDoSProtection("418 banned"))
    with pytest.raises(ExchangeRateLimitError):
        await _adapter("okx", client).fetch_tickers([])


async def test_error_does_not_chain_ccxt_cause() -> None:
    client = FakeCcxtClient("binance")
    secret_url = "https://api.binance.com/sapi/v1/x?timestamp=1&signature=deadbeef"
    client.fail("fetch_tickers", ccxt.AuthenticationError(f"binance GET {secret_url} 401"))
    with pytest.raises(ExchangeAuthError) as exc_info:
        await _adapter("binance", client).fetch_tickers([])
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


async def test_malformed_payload_maps_to_data_error() -> None:
    client = FakeCcxtClient("okx", fetch_tickers=lambda: {"BTC/USDT": {"bid": object()}})
    client.fail("fetch_order_book", KeyError("bids"))
    with pytest.raises(ExchangeDataError, match="malformed"):
        await _adapter("okx", client).fetch_order_book("BTC/USDT", 5)


async def test_malformed_levels_are_skipped() -> None:
    client = FakeCcxtClient(
        "okx",
        fetch_order_book={"bids": [[1], "x", [0.9, 2]], "asks": [[1.1, 1]], "timestamp": None},
    )
    book = await _adapter("okx", client).fetch_order_book("BTC/USDT", 5)
    assert book.best_bid == D("0.9")


async def test_bad_symbol_maps_to_data_error() -> None:
    client = FakeCcxtClient("okx")
    client.fail("fetch_order_book", ccxt.BadSymbol("nope"))
    with pytest.raises(ExchangeDataError):
        await _adapter("okx", client).fetch_order_book("NOPE/USDT", 5)


async def test_timeout_maps_to_unavailable() -> None:
    import asyncio

    client = FakeCcxtClient("okx")

    async def hang(*_: Any) -> Any:
        await asyncio.sleep(10)

    client.fetch_tickers = hang  # type: ignore[method-assign]
    adapter = _adapter("okx", client, timeout_ms=1_000)
    adapter.max_attempts = 1  # type: ignore[misc]
    with pytest.raises(ExchangeUnavailableError, match="timed out"):
        await asyncio.wait_for(adapter.fetch_tickers([]), timeout=5)


# ------------------------------------------------------------------ credentials


@pytest.mark.parametrize("exchange", ["okx", "kucoin", "bitget"])
def test_passphrase_required(exchange: str) -> None:
    with pytest.raises(ConfigurationError, match="passphrase"):
        _adapter(exchange, credentials=_creds(api_key="k", api_secret="s"))


def test_client_config_credentials_only_for_rest() -> None:
    adapter = _adapter("okx", credentials=_creds(api_key="k", api_secret="s", api_passphrase="p"))
    rest = adapter._client_config()
    ws = adapter._client_config(authenticated=False)
    assert (rest["apiKey"], rest["secret"], rest["password"]) == ("k", "s", "p")
    assert "apiKey" not in ws
    assert rest["enableRateLimit"] is True
    assert rest["options"]["defaultType"] == "spot"


async def test_close_closes_clients() -> None:
    client = FakeCcxtClient("okx")
    await _adapter("okx", client).close()
    assert client.closed


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1e-05, D("0.00001")),
        (0.1, D("0.1")),
        ("2.5", D("2.5")),
        (3, D(3)),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        ("abc", None),
        (True, None),
    ],
)
def test_to_decimal(value: Any, expected: D | None) -> None:
    assert to_decimal(value) == expected


async def test_watch_after_close_rejected() -> None:
    adapter = _adapter("okx")
    await adapter.close()
    with pytest.raises(ExchangeUnavailableError, match="closed"):
        await adapter.watch_order_book("BTC/USDT", 5)


@pytest.mark.parametrize(
    ("exchange", "static"),
    [
        ("binance", True),
        ("bybit", True),
        ("okx", True),
        ("kucoin", False),
        ("gateio", False),
        ("mexc", True),
        ("bitget", True),
    ],
)
async def test_static_library_fees_flagged_as_default(exchange: str, static: bool) -> None:
    btc = next(m for m in await _adapter(exchange).load_markets() if m.symbol == "BTC/USDT")
    assert btc.taker_fee_is_default is static


async def test_contract_and_currency_flags_parsed() -> None:
    client = FakeCcxtClient(
        "gateio",
        fetch_currencies={
            "USDT": {
                "withdraw": True,
                "deposit": False,
                "networks": {
                    "ERC20": {
                        "withdraw": True,
                        "deposit": True,
                        "fee": 1,
                        "info": {"addr": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
                    }
                },
            },
            "OLD": {"withdraw": False, "deposit": False, "networks": {}},
        },
    )
    info = await _adapter("gateio", client).load_transfer_info()
    assert info is not None
    assert info["USDT"].networks[0].contract == "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    assert info["USDT"].deposit_enabled is False
    assert info["OLD"].withdraw_enabled is False
    assert info["OLD"].networks == ()


def test_unsupported_precision_mode_rejected() -> None:
    client = FakeCcxtClient("okx")
    client.precisionMode = ccxt.DECIMAL_PLACES  # type: ignore[attr-defined]
    with pytest.raises(ConfigurationError, match="precision"):
        _adapter("okx", client)


@pytest.mark.parametrize(
    "kwargs", [{"fallback_taker_fee": D("0.2")}, {"fallback_taker_fee": D(0)}, {"timeout_ms": 0}]
)
def test_adapter_options_validation(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"fallback_taker_fee|timeout_ms"):
        AdapterOptions(**kwargs)


def test_adapter_options_from_settings_converts_percent() -> None:
    options = AdapterOptions.from_settings(timeout_ms=5_000, default_taker_fee_pct=D("0.2"))
    assert options.fallback_taker_fee == D("0.002")
