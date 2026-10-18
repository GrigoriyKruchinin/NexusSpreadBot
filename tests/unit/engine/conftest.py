from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal as D

import pytest

from nexus.domain.models import MarketInfo, OrderBook, PriceLevel
from nexus.engine.estimator import EstimatorConfig

NOW = 1_700_000_000_000


@dataclass
class FixedClock:
    now: int = NOW

    def now_ms(self) -> int:
        return self.now


def book(
    exchange: str,
    *,
    bids: Sequence[tuple[str, str]] = (),
    asks: Sequence[tuple[str, str]] = (),
    ts: int = NOW - 100,
    symbol: str = "ABC/USDT",
) -> OrderBook:
    return OrderBook(
        exchange=exchange,
        symbol=symbol,
        bids=tuple(PriceLevel(D(p), D(a)) for p, a in bids),
        asks=tuple(PriceLevel(D(p), D(a)) for p, a in asks),
        timestamp_ms=ts,
        received_at_ms=ts,
    )


def market(
    exchange: str,
    *,
    fee: str = "0.001",
    step: str | None = None,
    min_amount: str | None = None,
    min_cost: str | None = None,
    active: bool = True,
    symbol: str = "ABC/USDT",
) -> MarketInfo:
    base, quote = symbol.split("/")
    return MarketInfo(
        exchange=exchange,
        symbol=symbol,
        base=base,
        quote=quote,
        taker_fee=D(fee),
        amount_step=D(step) if step else None,
        min_amount=D(min_amount) if min_amount else None,
        min_cost=D(min_cost) if min_cost else None,
        active=active,
    )


@pytest.fixture
def config() -> EstimatorConfig:
    return EstimatorConfig(
        min_net_profit_pct=D("0.3"),
        min_net_profit_usd=D(5),
        reference_notional_usd=D(1000),
        max_orderbook_age_ms=5_000,
        max_book_skew_ms=3_000,
        max_gross_spread_pct=D(20),
        include_transfer_cost=True,
        require_verified_transfer=False,
    )
