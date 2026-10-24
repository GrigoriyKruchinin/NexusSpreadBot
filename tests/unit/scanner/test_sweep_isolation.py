"""R-02: one failing venue/route task never aborts the sweep; cancellation still propagates."""

import asyncio
from collections.abc import Sequence

import pytest

from nexus.domain.models import MarketInfo, OrderBook, Ticker
from nexus.scanner.service import gather_isolated
from tests.unit.scanner.test_scanner import Harness


@pytest.fixture
def h() -> Harness:
    harness = Harness()
    harness.a.quote("ABC/USDT", "99.9", "100")
    harness.b.quote("ABC/USDT", "101", "101.1")
    harness.c.quote("ABC/USDT", "100.05", "101.05")
    return harness


async def test_gather_isolated_maps_failures_to_none() -> None:
    async def ok() -> int:
        return 1

    async def boom() -> int:
        raise KeyError("x")

    assert await gather_isolated({"a": ok(), "b": boom()}, event="t") == {"a": 1, "b": None}


async def test_gather_isolated_propagates_a_cancelled_job() -> None:
    async def stop() -> int:
        raise asyncio.CancelledError

    async def ok() -> int:
        return 1

    with pytest.raises(asyncio.CancelledError):
        await gather_isolated({"a": ok(), "b": stop()}, event="t")


async def test_gather_isolated_propagates_cancellation() -> None:
    async def slow() -> int:
        await asyncio.sleep(10)
        return 1

    task = asyncio.create_task(gather_isolated({"a": slow()}, event="t"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_unexpected_ticker_error_on_one_venue_keeps_the_sweep(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken(symbols: Sequence[str]) -> dict[str, Ticker]:
        raise RuntimeError("ccxt parse failure")

    h.c.fetch_tickers = broken  # type: ignore[method-assign]
    result = await h.scanner.sweep()
    assert result.exchanges_ok == 2
    assert result.alerts == 1
    assert h.heartbeat.beats == ["scanner"]
    assert ("c", "fetch_tickers", False) in h.repos.health  # counted as a failed call


async def test_unexpected_ticker_error_counts_toward_down(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken(symbols: Sequence[str]) -> dict[str, Ticker]:
        raise RuntimeError("boom")

    h.c.fetch_tickers = broken  # type: ignore[method-assign]
    await h.scanner.sweep()
    await h.scanner.sweep()  # down_after_failures = 2
    assert any(getattr(e, "kind", "") == "exchange_down" for e in h.dispatcher.events)


async def test_unexpected_metadata_error_on_one_venue_keeps_others(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken() -> list[MarketInfo]:
        raise RuntimeError("parse")

    h.c.load_markets = broken  # type: ignore[method-assign]
    universe = await h.scanner.refresh_metadata()
    assert universe.symbols_for("c") == {"ABC/USDT"}  # previous markets kept
    assert universe.symbols_for("a") == {"ABC/USDT"}


async def test_unexpected_book_error_on_one_route_keeps_the_sweep(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def broken(symbol: str, depth: int) -> OrderBook:
        raise RuntimeError("book parse")

    h.c.fetch_order_book = broken  # type: ignore[method-assign]
    result = await h.scanner.sweep()
    assert result.alerts == 1  # the a>b route still alerts


async def test_sweep_cancellation_propagates(h: Harness) -> None:
    await h.scanner.refresh_metadata()

    async def hang(symbols: Sequence[str]) -> dict[str, Ticker]:
        await asyncio.sleep(10)
        return {}

    h.c.fetch_tickers = hang  # type: ignore[method-assign]
    task = asyncio.create_task(h.scanner.sweep())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
