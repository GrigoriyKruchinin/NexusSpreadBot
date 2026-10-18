"""Narrow market-data interfaces (ISP).

Trading capabilities live in a separate interface (``ITradeExecutor``, Stage 2). There is
intentionally **no** withdrawal or transfer interface anywhere in the system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import TracebackType
from typing import ClassVar, Self

from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, Ticker


class IRestMarketData(ABC):
    """Request/response market data."""

    @abstractmethod
    async def fetch_tickers(self, symbols: Sequence[str]) -> Mapping[str, Ticker]:
        """Fetch top-of-book tickers for ``symbols`` (missing symbols are omitted)."""

    @abstractmethod
    async def fetch_order_book(self, symbol: str, depth: int) -> OrderBook:
        """Fetch an order book snapshot with up to ``depth`` levels per side."""


class IWebSocketOrderbook(ABC):
    """Streaming order book updates."""

    @abstractmethod
    async def watch_order_book(self, symbol: str, depth: int) -> OrderBook:
        """Return the next order book update for ``symbol`` (subscribes on first call)."""

    @abstractmethod
    async def unwatch_order_book(self, symbol: str) -> None:
        """Unsubscribe from ``symbol`` (best effort; no-op when not subscribed)."""


class IMarketMetadata(ABC):
    """Market and asset metadata."""

    @abstractmethod
    async def load_markets(self) -> Sequence[MarketInfo]:
        """Load all active spot markets with fees and precision."""

    @abstractmethod
    async def load_transfer_info(self) -> Mapping[str, AssetTransferInfo] | None:
        """Load per-asset deposit/withdrawal network status (read-only metadata).

        Returns ``None`` when the exchange does not expose this data without credentials
        that are not configured.
        """


class ITradingFeeSource(ABC):
    """Per-symbol account-tier fee lookups (for exchanges without a bulk fee endpoint)."""

    @abstractmethod
    async def fetch_taker_fee(self, symbol: str) -> Decimal | None:
        """Account taker fee of ``symbol`` as a fraction, or ``None`` if unavailable.

        Requires read-only credentials; raises ``ExchangeError`` on transport failures.
        """


class BaseExchangeAdapter(IRestMarketData, IMarketMetadata, ABC):
    """Base class for centralized exchange adapters.

    A new exchange is added by subclassing this (or a shared implementation such as the ccxt
    adapter) and registering it in :mod:`nexus.adapters.registry`; no orchestrator change is
    required.
    """

    name: ClassVar[str]

    @abstractmethod
    async def close(self) -> None:
        """Release network resources."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
