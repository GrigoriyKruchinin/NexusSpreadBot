"""In-memory test doubles for interfaces."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal as D

from nexus.domain.errors import ExchangeError
from nexus.domain.events import SystemEvent
from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, PriceLevel, Ticker
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import RouteQuote
from nexus.interfaces.coordination import IAlertDispatcher, ICooldownStore, IHeartbeat
from nexus.interfaces.market_data import BaseExchangeAdapter
from nexus.interfaces.notifications import DeliveryReceipt, INotifier, OutgoingMessage
from nexus.interfaces.repositories import (
    AlertDeliveryStatus,
    IAlertLogRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    IRetentionRepository,
    ISnapshotRepository,
)


@dataclass
class ManualClock:
    now: int = 1_800_000_000_000

    def now_ms(self) -> int:
        return self.now


class FakeExchange(BaseExchangeAdapter):
    """Configurable exchange: books are built from (bid, ask) with deep levels."""

    name = "fake"

    def __init__(self, name: str, clock: ManualClock, *, fee: str = "0.001") -> None:
        self.exchange = name
        self.clock = clock
        self.fee = D(fee)
        self.quotes: dict[str, tuple[str, str]] = {}
        self.book_quotes: dict[str, tuple[str, str]] = {}
        """Order book (bid, ask) overrides, e.g. when the book disagrees with the ticker."""
        self.transfers: dict[str, AssetTransferInfo] | None = None
        self.ticker_errors: list[ExchangeError] = []
        self.book_errors: dict[str, ExchangeError] = {}
        self.ticker_calls = 0
        self.book_calls: list[str] = []
        self.closed = False

    def quote(self, symbol: str, bid: str, ask: str) -> None:
        self.quotes[symbol] = (bid, ask)

    async def load_markets(self) -> Sequence[MarketInfo]:
        return [
            MarketInfo(
                exchange=self.exchange,
                symbol=s,
                base=s.split("/")[0],
                quote=s.split("/")[1],
                taker_fee=self.fee,
            )
            for s in self.quotes
        ]

    async def load_transfer_info(self) -> Mapping[str, AssetTransferInfo] | None:
        return self.transfers

    async def fetch_tickers(self, symbols: Sequence[str]) -> Mapping[str, Ticker]:
        self.ticker_calls += 1
        if self.ticker_errors:
            raise self.ticker_errors.pop(0)
        return {
            s: Ticker(
                exchange=self.exchange,
                symbol=s,
                bid=D(b),
                ask=D(a),
                quote_volume_24h=D(10_000_000),
                timestamp_ms=self.clock.now,
            )
            for s, (b, a) in self.quotes.items()
            if s in symbols
        }

    async def fetch_order_book(self, symbol: str, depth: int) -> OrderBook:
        self.book_calls.append(symbol)
        if symbol in self.book_errors:
            raise self.book_errors[symbol]
        bid, ask = (D(x) for x in self.book_quotes.get(symbol, self.quotes[symbol]))
        return OrderBook(
            exchange=self.exchange,
            symbol=symbol,
            bids=(PriceLevel(bid, D(1_000)),),
            asks=(PriceLevel(ask, D(1_000)),),
            timestamp_ms=self.clock.now - 50,
            received_at_ms=self.clock.now,
        )

    async def close(self) -> None:
        self.closed = True


@dataclass
class MemoryRepos(
    IMarketRepository,
    ISnapshotRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IAlertLogRepository,
    IRetentionRepository,
):
    markets: list[MarketInfo] = field(default_factory=list)
    snapshots: list[RouteQuote] = field(default_factory=list)
    evaluations: dict[int, SpreadEvaluation] = field(default_factory=dict)
    health: list[tuple[str, str, bool]] = field(default_factory=list)
    alerts: dict[int, tuple[AlertDeliveryStatus, str | None]] = field(default_factory=dict)
    purged: list[tuple[datetime, datetime]] = field(default_factory=list)

    async def upsert_markets(self, markets: Sequence[MarketInfo]) -> int:
        self.markets = list(markets)
        return len(markets)

    async def add_snapshots(self, captured_at: datetime, routes: Sequence[RouteQuote]) -> int:
        self.snapshots.extend(routes)
        return len(routes)

    async def add_evaluations(self, evaluations: Sequence[SpreadEvaluation]) -> list[int]:
        ids = []
        for evaluation in evaluations:
            new_id = len(self.evaluations) + 1
            self.evaluations[new_id] = evaluation
            ids.append(new_id)
        return ids

    async def get(self, evaluation_id: int) -> SpreadEvaluation | None:
        return self.evaluations.get(evaluation_id)

    async def record(self, *args: object, **kwargs: object) -> None:
        if "channel" in kwargs:  # alert log
            evaluation_id = int(str(args[0]))
            status = kwargs["status"]
            assert isinstance(status, AlertDeliveryStatus)
            error = kwargs.get("error")
            self.alerts[evaluation_id] = (status, error if isinstance(error, str) else None)
        else:  # exchange health
            self.health.append((str(args[0]), str(args[1]), bool(kwargs["ok"])))

    async def claim(self, evaluation_id: int, *, channel: str) -> bool:
        entry = self.alerts.get(evaluation_id)
        if entry is not None and entry[0] is not AlertDeliveryStatus.FAILED:
            return False
        self.alerts[evaluation_id] = (AlertDeliveryStatus.SENDING, None)
        return True

    async def purge(
        self, *, snapshots_before: datetime, evaluations_before: datetime
    ) -> dict[str, int]:
        self.purged.append((snapshots_before, evaluations_before))
        return {"spread_snapshots": 0}


class MemoryCooldowns(ICooldownStore):
    def __init__(self) -> None:
        self.active: set[str] = set()

    async def acquire(self, key: str, ttl_s: int) -> bool:
        if key in self.active:
            return False
        self.active.add(key)
        return True

    async def release(self, key: str) -> None:
        self.active.discard(key)


class MemoryHeartbeat(IHeartbeat):
    def __init__(self) -> None:
        self.beats: list[str] = []

    async def beat(self, service: str, ttl_s: int) -> None:
        self.beats.append(service)

    async def last_beat_ms(self, service: str) -> int | None:
        return 1 if service in self.beats else None


class RecordingDispatcher(IAlertDispatcher):
    def __init__(self) -> None:
        self.opportunities: list[int] = []
        self.events: list[SystemEvent] = []

    async def dispatch_opportunity(self, evaluation_id: int) -> None:
        self.opportunities.append(evaluation_id)

    async def dispatch_event(self, event: SystemEvent) -> None:
        self.events.append(event)


class RecordingNotifier(INotifier):
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[OutgoingMessage] = []
        self.error = error

    async def send(self, message: OutgoingMessage) -> DeliveryReceipt:
        if self.error:
            raise self.error
        self.sent.append(message)
        return DeliveryReceipt(channel="telegram", message_id=str(len(self.sent)))

    async def close(self) -> None:
        return None
