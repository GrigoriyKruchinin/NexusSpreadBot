"""Narrow, read-only perpetual-swap market-data port (ADR 0009).

There are intentionally no account, order, leverage, margin or transfer methods here, and
implementations are built without credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import ClassVar, Self

from nexus.domain.models import OrderBook
from nexus.domain.perp import (
    FundingInfo,
    FundingPayment,
    LeverageTier,
    MarkKline,
    PerpMarket,
    PerpTicker,
)


class IPerpMarketData(ABC):
    """Public perp market data of one venue. Order book amounts are in base units."""

    name: ClassVar[str]

    @abstractmethod
    async def load_perp_markets(self) -> Sequence[PerpMarket]:
        """Linear USDT perpetuals only (inactive ones included, flagged)."""

    @abstractmethod
    async def fetch_perp_tickers(self) -> Mapping[str, PerpTicker]:
        """All perp tickers (one request where the venue allows)."""

    @abstractmethod
    async def fetch_perp_order_book(self, symbol: str, depth: int) -> OrderBook:
        """Order book snapshot with up to ``depth`` levels per side, amounts in base units."""

    @abstractmethod
    async def fetch_funding(
        self, symbols: Sequence[str] | None = None
    ) -> Mapping[str, FundingInfo]:
        """Current funding/mark/index (``None`` = all symbols the venue serves in bulk)."""

    @abstractmethod
    async def fetch_mark_klines(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[MarkKline]:
        """1 m mark-price candles in ``[since_ms, until_ms)``, ascending, paged internally."""

    @abstractmethod
    async def fetch_funding_history(
        self, symbol: str, since_ms: int, until_ms: int
    ) -> Sequence[FundingPayment]:
        """Settled funding rates in ``[since_ms, until_ms)``, ascending."""

    @abstractmethod
    async def fetch_leverage_tiers(self, symbol: str) -> Sequence[LeverageTier] | None:
        """Public maintenance-margin tiers, or ``None`` when the venue serves them only signed."""

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
