"""Perp market-data adapters on recorded public fixtures (no network, no credentials)."""

import copy
from decimal import Decimal as D
from typing import Any

import ccxt
import pytest

import nexus.adapters.perp  # noqa: F401 - registers adapters
from nexus.adapters.perp.ccxt_perp import CcxtPerpAdapter
from nexus.adapters.perp.okx_swap import OkxSwapAdapter
from nexus.adapters.perp.registry import perp_registry
from nexus.adapters.registry import AdapterOptions
from nexus.domain.errors import (
    ExchangeDataError,
    ExchangeRateLimitError,
    ExchangeUnavailableError,
    ReadOnlyViolationError,
)
from tests.unit.adapters.fake_perp import FakePerpClient, load_perp_fixture

NOW = 1_800_000_000_000
VENUES = ("okx",)
CLASSES: dict[str, type[CcxtPerpAdapter]] = {"okx": OkxSwapAdapter}
BTC = "BTC/USDT:USDT"


class _Clock:
    def __init__(self) -> None:
        self.value = NOW

    def now_ms(self) -> int:
        return self.value


def _adapter(
    venue: str, client: FakePerpClient | None = None, **overrides: Any
) -> tuple[CcxtPerpAdapter, FakePerpClient, _Clock]:
    client = client or FakePerpClient(venue, **overrides)
    clock = _Clock()
    adapter = CLASSES[venue](AdapterOptions(), clock=clock, rest_client=client)
    adapter.retry_backoff_s = 0.0  # type: ignore[misc]
    return adapter, client, clock


# ------------------------------------------------------------------ safety


@pytest.mark.parametrize("venue", VENUES)
async def test_real_client_has_no_credentials_and_guard(venue: str) -> None:
    adapter = perp_registry.create(venue, AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        assert not client.apiKey
        assert not client.secret
        assert not client.password
        assert client.nexus_read_only_guard is True
        assert client.has.get("fetchCurrencies") in (True, None, False)
        assert client.options.get("fetchCurrencies") is False
        for method in ("POST", "DELETE", "PUT", "post"):
            with pytest.raises(ReadOnlyViolationError):
                await client.fetch("https://example.invalid/api", method)
        with pytest.raises(ReadOnlyViolationError):
            await client.request("anything", "public", "POST", {})
        with pytest.raises(ReadOnlyViolationError):
            await client.request("anything", "public", "DELETE", {})
    finally:
        await adapter.close()


@pytest.mark.parametrize("venue", VENUES)
async def test_implicit_private_trading_method_is_unreachable(venue: str) -> None:
    adapter = perp_registry.create(venue, AdapterOptions())
    try:
        client = adapter._rest  # type: ignore[attr-defined]
        trade = {
            "okx": "privatePostTradeOrder",
            "kucoin": "futuresPrivatePostOrders",
            "binance": "fapiPrivatePostOrder",
        }[venue]
        # Either the missing credentials or the read-only guard stops it before any I/O.
        with pytest.raises((ccxt.AuthenticationError, ReadOnlyViolationError)):
            await getattr(client, trade)({})
    finally:
        await adapter.close()


def test_adapter_refuses_client_with_credentials() -> None:
    client = FakePerpClient("okx")
    client.apiKey = "k"  # type: ignore[assignment]
    with pytest.raises(ReadOnlyViolationError):
        _adapter("okx", client)


def test_port_has_no_credentials_in_factory_signature() -> None:
    import inspect

    cls = type(perp_registry.create("okx", AdapterOptions()))
    assert list(inspect.signature(cls.__init__).parameters) == [
        "self",
        "options",
        "clock",
        "rest_client",
    ]


# ------------------------------------------------------------------ markets


@pytest.mark.parametrize("venue", VENUES)
async def test_markets_linear_usdt_only(venue: str) -> None:
    adapter, _, _ = _adapter(venue)
    markets = {m.symbol: m for m in await adapter.load_perp_markets()}
    assert BTC in markets
    assert all(s.endswith("/USDT:USDT") for s in markets)
    assert not any(s.startswith(("BTC/USD:", "ETH/USD:")) for s in markets)
    btc = markets[BTC]
    assert btc.base == "BTC"
    assert btc.active
    assert not btc.delisting
    assert btc.max_leverage is not None
    assert btc.taker_fee is not None
    assert btc.contract_size > 0
    assert btc.amount_step > 0


async def test_okx_contract_conversion_and_flags() -> None:
    adapter, _, _ = _adapter("okx")
    markets = {m.symbol: m for m in await adapter.load_perp_markets()}
    btc = markets[BTC]
    assert btc.contract_size == D("0.01")
    assert btc.amount_step == D("0.01")
    assert btc.lot_base == D("0.0001")
    assert btc.max_leverage == D("100.0")
    assert btc.taker_fee == D("0.0005")
    doge = markets["DOGE/USDT:USDT"]
    assert doge.contract_size == D("1000.0")


async def test_okx_delisting_and_inactive_flags() -> None:
    raw = load_markets_with("okx", lambda m: m["info"].update(expTime="1900000000000"), BTC)
    raw["ETH/USDT:USDT"]["active"] = False
    adapter, _, _ = _adapter("okx", markets=raw)
    markets = {m.symbol: m for m in await adapter.load_perp_markets()}
    assert markets[BTC].delisting
    assert not markets["ETH/USDT:USDT"].active


def load_markets_with(venue: str, mutate: Any, symbol: str) -> dict[str, Any]:
    raw: dict[str, Any] = copy.deepcopy(load_perp_fixture(venue, "markets"))
    mutate(raw[symbol])
    return raw


async def test_market_with_non_usdt_settle_or_bad_data_skipped() -> None:
    raw = load_perp_fixture("okx", "markets")
    raw = copy.deepcopy(raw)
    raw["ETH/USDT:USDT"]["settle"] = "USDC"
    raw["DOGE/USDT:USDT"]["precision"]["amount"] = None
    raw["A/USDT:USDT"]["contractSize"] = 0
    adapter, _, _ = _adapter("okx", markets=raw)
    symbols = {m.symbol for m in await adapter.load_perp_markets()}
    assert symbols == {BTC, "2Z/USDT:USDT"}


# ------------------------------------------------------------------ tickers / book


async def test_tickers_parsed_and_stamped_at_request_start() -> None:
    adapter, client, clock = _adapter("okx")
    raw = load_perp_fixture("okx", "tickers")
    tickers = await adapter.fetch_perp_tickers()
    assert tickers[BTC].bid == D(str(raw[BTC]["bid"]))
    assert tickers[BTC].ask == D(str(raw[BTC]["ask"]))
    assert tickers[BTC].received_at_ms == NOW
    assert tickers[BTC].mark is None
    assert [c[0] for c in client.calls].count("load_markets") == 1
    clock.value += 5
    await adapter.fetch_perp_tickers()
    assert [c[0] for c in client.calls].count("load_markets") == 1  # markets cached


async def test_tickers_skip_unknown_crossed_and_empty() -> None:
    raw = copy.deepcopy(load_perp_fixture("okx", "tickers"))
    raw["ETH/USDT:USDT"]["bid"] = raw["ETH/USDT:USDT"]["ask"]  # crossed
    raw["DOGE/USDT:USDT"]["bid"] = None
    raw["NOPE/USDT:USDT"] = raw[BTC]
    adapter, _, _ = _adapter("okx", tickers=raw)
    tickers = await adapter.fetch_perp_tickers()
    assert "ETH/USDT:USDT" not in tickers
    assert "NOPE/USDT:USDT" not in tickers
    assert tickers["DOGE/USDT:USDT"].bid is None


async def test_okx_order_book_in_base_units() -> None:
    adapter, client, _ = _adapter("okx")
    book = await adapter.fetch_perp_order_book(BTC, 5)
    raw = load_perp_fixture("okx", "order_book")
    assert book.bids[0].price == D("80207.0")
    assert book.bids[0].amount == D("103.41") * D("0.01")
    assert len(book.bids) == 5
    assert book.timestamp_ms == raw["timestamp"]
    assert book.received_at_ms == NOW
    assert client.calls[-1] == ("fetch_order_book", (BTC, 5))


async def test_order_book_unknown_symbol_and_depth_limit() -> None:
    adapter, _, _ = _adapter("okx")
    with pytest.raises(ExchangeDataError):
        await adapter.fetch_perp_order_book("NOPE/USDT:USDT", 5)
    assert adapter.order_book_limit(1000) == 400


async def test_order_book_crossed_is_data_error() -> None:
    raw = {"bids": [[10, 1]], "asks": [[9, 1]], "timestamp": None}
    adapter, _, _ = _adapter("okx", order_book=raw)
    with pytest.raises(ExchangeDataError):
        await adapter.fetch_perp_order_book(BTC, 5)


# ------------------------------------------------------------------ funding


async def test_okx_funding_per_instrument_with_bulk_marks() -> None:
    adapter, client, _ = _adapter("okx")
    funding = await adapter.fetch_funding([BTC, "NOPE/USDT:USDT"])
    info = funding[BTC]
    assert info.rate == D("8.96286672347E-5")
    assert info.mark_price == D("80215.9")
    assert info.interval_h == D("8")
    assert info.next_funding_ms is not None
    assert info.received_at_ms == NOW
    names = [c[0] for c in client.calls]
    assert names.count("fetch_funding_rate") == 1  # unknown symbol is not requested
    assert names.count("fetch_mark_prices") == 1
    assert await adapter.fetch_funding(None) == {}


async def test_okx_funding_one_instrument_failure_is_isolated() -> None:
    adapter, client, _ = _adapter("okx")
    client.fail("fetch_funding_rate", ccxt.BadSymbol("gone"))
    funding = await adapter.fetch_funding([BTC, "ETH/USDT:USDT"])
    assert set(funding) == {"ETH/USDT:USDT"}


async def test_funding_negative_rate_keeps_sign() -> None:
    raw = copy.deepcopy(load_perp_fixture("okx", "funding"))
    raw[BTC]["fundingRate"] = -0.0036
    adapter, _, _ = _adapter("okx", funding=raw)
    assert (await adapter.fetch_funding([BTC]))[BTC].rate == D("-0.0036")


# ------------------------------------------------------------------ history


def _rows(start: int, count: int) -> list[list[float]]:
    return [[start + i * 60_000, 10.0, 11.0, 9.0, 10.5, 0.0] for i in range(count)]


def _paged(rows: list[list[float]]) -> Any:
    def respond(symbol: str, timeframe: str, since: int, limit: int) -> list[list[float]]:
        return [r for r in rows if r[0] >= since][:limit]

    return respond


async def test_klines_paged_ranged_and_ascending() -> None:
    start = NOW - NOW % 60_000
    rows = _rows(start, 250)
    adapter, client, _ = _adapter("okx", klines=_paged(rows))
    klines = await adapter.fetch_mark_klines(BTC, start + 30 * 60_000, start + 200 * 60_000)
    assert [k.open_ms for k in klines] == [start + i * 60_000 for i in range(30, 200)]
    assert len(klines) == 170
    assert klines[0].high == D("11.0")
    assert [c[0] for c in client.calls].count("fetch_mark_ohlcv") == 2  # 100 + 70 rows


async def test_klines_stop_without_progress_and_skip_garbage() -> None:
    start = NOW - NOW % 60_000
    bad = [[start, 10.0, 9.0, 11.0, 10.0, 0.0], [start + 60_000, None, 1, 1, 1, 0], "x", [1]]
    adapter, client, _ = _adapter("okx", klines=lambda *a: bad)
    assert await adapter.fetch_mark_klines(BTC, start, start + 600_000) == ()
    assert [c[0] for c in client.calls].count("fetch_mark_ohlcv") == 1


async def test_funding_history_paged() -> None:
    base = NOW - NOW % 3_600_000
    rows = [
        {"fundingRate": 0.0001 * ((-1) ** i), "timestamp": base + i * 8 * 3_600_000}
        for i in range(250)
    ]

    def respond(symbol: str, since: int, limit: int) -> list[dict[str, Any]]:
        return [r for r in rows if r["timestamp"] >= since][:limit]

    adapter, client, _ = _adapter("okx", funding_history=respond)
    payments = await adapter.fetch_funding_history(BTC, base, base + 120 * 8 * 3_600_000)
    assert len(payments) == 120
    assert payments[0].rate == D("0.0001")
    assert payments[1].rate == D("-0.0001")
    assert [p.funding_time_ms for p in payments] == sorted(p.funding_time_ms for p in payments)
    assert [c[0] for c in client.calls].count("fetch_funding_rate_history") == 2


async def test_okx_leverage_tiers_sorted() -> None:
    adapter, _, _ = _adapter("okx")
    tiers = await adapter.fetch_leverage_tiers(BTC)
    assert tiers is not None
    assert tiers[0].min_notional == D("0.0")
    assert tiers[0].mmr == D("0.004")
    assert [t.min_notional for t in tiers] == sorted(t.min_notional for t in tiers)


# ------------------------------------------------------------------ errors


@pytest.mark.parametrize("venue", VENUES)
async def test_rate_limit_is_translated_and_not_retried(venue: str) -> None:
    adapter, client, _ = _adapter(venue)
    await adapter.load_perp_markets()
    client.fail("fetch_tickers", ccxt.RateLimitExceeded("429 https://x/y?sig=abc"))
    client.fail("fetch_bids_asks", ccxt.RateLimitExceeded("429 https://x/y?sig=abc"))
    with pytest.raises(ExchangeRateLimitError) as caught:
        await adapter.fetch_perp_tickers()
    assert "sig=abc" not in str(caught.value)
    calls = [c[0] for c in client.calls]
    assert calls.count("fetch_tickers") + calls.count("fetch_bids_asks") == 1


@pytest.mark.parametrize("venue", VENUES)
async def test_network_errors_retried_then_unavailable(venue: str) -> None:
    adapter, client, _ = _adapter(venue)
    client.fail("load_markets", *[ccxt.NetworkError("boom")] * 3)
    with pytest.raises(ExchangeUnavailableError):
        await adapter.load_perp_markets()
    assert [c[0] for c in client.calls].count("load_markets") == 3
    client.fail("load_markets", ccxt.NetworkError("boom"))
    assert await adapter.load_perp_markets()  # retried once, then served


async def test_malformed_payload_is_data_error() -> None:
    adapter, _, _ = _adapter("okx", markets={"X": 5})
    assert await adapter.load_perp_markets() == ()
    adapter2, _, _ = _adapter("okx", order_book=lambda *a: 5)
    with pytest.raises(ExchangeDataError):
        await adapter2.fetch_perp_order_book(BTC, 5)


async def test_close_closes_client() -> None:
    adapter, client, _ = _adapter("okx")
    async with adapter:
        pass
    assert client.closed
