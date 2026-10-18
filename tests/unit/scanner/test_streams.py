import asyncio
from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.errors import ExchangeDataError, ExchangeUnavailableError
from nexus.domain.models import OrderBook, PriceLevel
from nexus.interfaces.market_data import IWebSocketOrderbook
from nexus.scanner.streams import OrderBookStreams
from tests.fakes import FakeExchange, ManualClock


class StreamingExchange(FakeExchange, IWebSocketOrderbook):
    """Each ``watch`` call returns the next queued book (or raises the queued error)."""

    def __init__(self, name: str, clock: ManualClock) -> None:
        super().__init__(name, clock)
        self.updates: dict[str, asyncio.Queue[OrderBook | Exception]] = {}
        self.unwatched: list[str] = []
        self.watch_calls = 0

    def push(self, symbol: str, item: OrderBook | Exception) -> None:
        self.updates.setdefault(symbol, asyncio.Queue()).put_nowait(item)

    async def watch_order_book(self, symbol: str, depth: int) -> OrderBook:
        self.watch_calls += 1
        item = await self.updates.setdefault(symbol, asyncio.Queue()).get()
        if isinstance(item, Exception):
            raise item
        return item

    async def unwatch_order_book(self, symbol: str) -> None:
        self.unwatched.append(symbol)


def _book(clock: ManualClock, exchange: str = "a", symbol: str = "ABC/USDT") -> OrderBook:
    return OrderBook(
        exchange=exchange,
        symbol=symbol,
        bids=(PriceLevel(D(99), D(1)),),
        asks=(PriceLevel(D(100), D(1)),),
        timestamp_ms=clock.now,
        received_at_ms=clock.now,
    )


def _streams(
    clock: ManualClock, exchange: FakeExchange, *, max_streams: int = 2
) -> OrderBookStreams:
    return OrderBookStreams(
        {"a": exchange},
        depth=20,
        max_streams=max_streams,
        hot_ttl_ms=60_000,
        max_book_age_ms=1_000,
        clock=clock,
        error_backoff_s=0,
        max_consecutive_errors=2,
    )


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_streamed_book_served_while_fresh() -> None:
    clock = ManualClock()
    exchange = StreamingExchange("a", clock)
    streams = _streams(clock, exchange)
    streams.mark_hot("a", "ABC/USDT")
    assert streams.fresh_book("a", "ABC/USDT") is None  # nothing received yet
    book = _book(clock)
    exchange.push("ABC/USDT", book)
    await _settle()
    assert streams.fresh_book("a", "ABC/USDT") == replace(book, streamed=True)
    clock.now += 1_001
    assert streams.fresh_book("a", "ABC/USDT") is None  # too old: REST fallback
    await streams.close()
    assert exchange.unwatched == ["ABC/USDT"]
    assert streams.active == 0


async def test_streams_expire_and_are_bounded() -> None:
    clock = ManualClock()
    exchange = StreamingExchange("a", clock)
    streams = _streams(clock, exchange)
    for symbol in ("A/USDT", "B/USDT", "C/USDT"):
        streams.mark_hot("a", symbol)
    assert streams.active == 2  # bounded
    clock.now += 30_000
    streams.mark_hot("a", "A/USDT")  # extended
    clock.now += 30_000
    await streams.prune()
    assert exchange.unwatched == ["B/USDT"]
    assert streams.active == 1
    clock.now += 30_000
    await streams.prune()
    assert streams.active == 0


async def test_failing_stream_given_up_until_expiry() -> None:
    clock = ManualClock()
    exchange = StreamingExchange("a", clock)
    streams = _streams(clock, exchange)
    streams.mark_hot("a", "ABC/USDT")
    exchange.push("ABC/USDT", _book(clock))
    exchange.push("ABC/USDT", ExchangeUnavailableError("a", "ws closed"))
    exchange.push("ABC/USDT", ExchangeUnavailableError("a", "ws closed"))
    await _settle()
    assert streams.fresh_book("a", "ABC/USDT") is None  # dropped on error
    assert streams.active == 0  # given up: no longer holds a slot
    calls = exchange.watch_calls
    streams.mark_hot("a", "ABC/USDT")  # not restarted (nor extended) before expiry
    await _settle()
    assert exchange.watch_calls == calls
    clock.now += 60_000
    await streams.prune()
    streams.mark_hot("a", "ABC/USDT")  # expired: may restart
    assert streams.active == 1
    await streams.close()


async def test_invalid_book_triggers_resubscribe() -> None:
    clock = ManualClock()
    exchange = StreamingExchange("a", clock)
    streams = _streams(clock, exchange)
    streams.mark_hot("a", "ABC/USDT")
    exchange.push("ABC/USDT", ExchangeDataError("a", "crossed order book"))
    book = _book(clock)
    exchange.push("ABC/USDT", book)
    await _settle()
    assert exchange.unwatched == ["ABC/USDT"]  # cache resynced from a fresh snapshot
    assert streams.fresh_book("a", "ABC/USDT") == replace(book, streamed=True)
    await streams.close()


async def test_stop_propagates_callers_cancellation() -> None:
    clock = ManualClock()
    exchange = StreamingExchange("a", clock)
    streams = _streams(clock, exchange)
    streams.mark_hot("a", "ABC/USDT")
    await _settle()
    closer = asyncio.create_task(streams.close())
    await asyncio.sleep(0)
    closer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closer


async def test_non_streaming_adapter_ignored() -> None:
    clock = ManualClock()
    streams = _streams(clock, FakeExchange("a", clock))
    streams.mark_hot("a", "ABC/USDT")
    assert streams.active == 0
    await streams.close()
