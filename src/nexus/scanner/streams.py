"""WebSocket hot-set: stream order books of recently profitable routes.

Routes that just evaluated with a positive net spread tend to stay interesting for a while.
For their legs the scanner keeps a WebSocket subscription open, so the next sweeps evaluate
them on a book that is milliseconds old instead of waiting for a REST snapshot. Streams expire
after ``hot_ttl_ms`` without a new positive evaluation, and the set is bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace

import structlog

from nexus.domain.clock import Clock
from nexus.domain.errors import DataValidationError, ExchangeDataError, ExchangeError
from nexus.domain.models import OrderBook
from nexus.interfaces.market_data import BaseExchangeAdapter, IWebSocketOrderbook

log = structlog.get_logger(__name__)

StreamKey = tuple[str, str]
UNWATCH_TIMEOUT_S = 2.0


class OrderBookStreams:
    """Bounded set of per-(exchange, symbol) WebSocket order book watchers."""

    def __init__(
        self,
        adapters: Mapping[str, BaseExchangeAdapter],
        *,
        depth: int,
        max_streams: int,
        hot_ttl_ms: int,
        max_book_age_ms: int,
        clock: Clock,
        error_backoff_s: float = 5.0,
        max_consecutive_errors: int = 5,
    ) -> None:
        """Create the stream set.

        Args:
            adapters: exchange adapters; only those implementing ``IWebSocketOrderbook`` stream.
            depth: order book levels per side.
            max_streams: upper bound of concurrent subscriptions (all exchanges).
            hot_ttl_ms: a stream is closed this long after its last ``mark_hot``.
            max_book_age_ms: streamed books older than this are not served (REST fallback).
            clock: time source.
            error_backoff_s: pause after a failed ``watch`` call.
            max_consecutive_errors: give up a stream (until it expires) after this many errors.
        """
        self._adapters = {
            name: adapter
            for name, adapter in adapters.items()
            if isinstance(adapter, IWebSocketOrderbook)
        }
        self._depth = depth
        self._max_streams = max_streams
        self._hot_ttl_ms = hot_ttl_ms
        self._max_book_age_ms = max_book_age_ms
        self._clock = clock
        self._error_backoff_s = error_backoff_s
        self._max_errors = max_consecutive_errors
        self._tasks: dict[StreamKey, asyncio.Task[None]] = {}
        self._expires_at: dict[StreamKey, int] = {}
        self._books: dict[StreamKey, OrderBook] = {}

    @property
    def active(self) -> int:
        """Number of running streams."""
        return len(self._tasks)

    def mark_hot(self, exchange: str, symbol: str) -> None:
        """Start streaming ``symbol`` on ``exchange`` or extend its lifetime."""
        key = (exchange, symbol)
        adapter = self._adapters.get(exchange)
        if adapter is None:
            return
        expires_at = self._clock.now_ms() + self._hot_ttl_ms
        if key in self._expires_at:
            if key in self._tasks:  # a given-up stream is left to expire, then may restart
                self._expires_at[key] = expires_at
            return
        if len(self._tasks) >= self._max_streams:
            return
        self._expires_at[key] = expires_at
        self._tasks[key] = asyncio.create_task(self._watch(key, adapter))
        log.info("book_stream_started", exchange=exchange, symbol=symbol)

    def fresh_book(self, exchange: str, symbol: str) -> OrderBook | None:
        """Latest streamed book if it is fresh enough to be evaluated."""
        book = self._books.get((exchange, symbol))
        if book is None or book.age_ms(self._clock.now_ms()) > self._max_book_age_ms:
            return None
        return book

    async def prune(self) -> None:
        """Close streams whose hot period has expired."""
        now = self._clock.now_ms()
        expired = [key for key, expires_at in self._expires_at.items() if expires_at <= now]
        await asyncio.gather(*(self._stop(key) for key in expired))

    async def close(self) -> None:
        """Close every stream."""
        await asyncio.gather(*(self._stop(key) for key in list(self._expires_at)))

    async def _stop(self, key: StreamKey) -> None:
        self._expires_at.pop(key, None)
        self._books.pop(key, None)
        task = self._tasks.pop(key, None)
        if task is not None:
            task.cancel()
            # ``wait`` does not re-raise the child's outcome, while a cancellation of the
            # caller itself still propagates (unlike suppressing CancelledError).
            await asyncio.wait({task})
        await self._unwatch(key)
        log.info("book_stream_stopped", exchange=key[0], symbol=key[1])

    async def _watch(self, key: StreamKey, adapter: IWebSocketOrderbook) -> None:
        exchange, symbol = key
        errors = 0
        while True:
            try:
                book = await adapter.watch_order_book(symbol, self._depth)
            except (ExchangeError, DataValidationError) as exc:
                self._books.pop(key, None)
                errors += 1
                log.info(
                    "book_stream_error",
                    exchange=exchange,
                    symbol=symbol,
                    errors=errors,
                    error=str(exc),
                )
                if errors >= self._max_errors:
                    self._give_up(key)
                    return
                if isinstance(exc, ExchangeDataError | DataValidationError):
                    # Crossed / invalid book: the local cache is out of sync. Resubscribing
                    # makes ccxt start again from a fresh snapshot.
                    await self._unwatch(key)
                await asyncio.sleep(self._error_backoff_s)
                continue
            except Exception:
                self._books.pop(key, None)
                log.exception("book_stream_failed", exchange=exchange, symbol=symbol)
                self._give_up(key)
                return
            errors = 0
            self._books[key] = replace(book, streamed=True)

    def _give_up(self, key: StreamKey) -> None:
        """Stop counting a failed stream; its key stays until expiry to avoid restart loops."""
        self._tasks.pop(key, None)
        log.warning("book_stream_given_up", exchange=key[0], symbol=key[1])

    async def _unwatch(self, key: StreamKey) -> None:
        try:
            await asyncio.wait_for(
                self._adapters[key[0]].unwatch_order_book(key[1]), UNWATCH_TIMEOUT_S
            )
        except Exception as exc:
            log.info("book_stream_unwatch_failed", exchange=key[0], symbol=key[1], error=repr(exc))
