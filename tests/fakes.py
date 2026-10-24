"""In-memory test doubles for interfaces."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal as D

from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.errors import ExchangeError
from nexus.domain.events import AlertContext, SystemEvent
from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, PriceLevel, Ticker
from nexus.domain.quarantine import RouteQuarantine
from nexus.domain.spread import SpreadEvaluation
from nexus.engine.candidates import RouteQuote
from nexus.interfaces.coordination import (
    IAlertDispatcher,
    ICooldownStore,
    IHeartbeat,
    IQuarantineStore,
)
from nexus.interfaces.market_data import BaseExchangeAdapter
from nexus.interfaces.notifications import DeliveryReceipt, INotifier, OutgoingMessage
from nexus.interfaces.repositories import (
    AlertDeliveryStatus,
    CapStatsDelta,
    IAlertLogRepository,
    IEpisodeRepository,
    IEvaluationRepository,
    IExchangeHealthRepository,
    IMarketRepository,
    IPaperRepository,
    IQuarantineRepository,
    IRetentionRepository,
    ISnapshotRepository,
    PaperHolding,
    PaperState,
    PortfolioRun,
    RunDefinition,
)
from nexus.simulation.portfolio import Rebalance, RebalanceStatus, TradeOutcome


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
    purged: list[tuple[datetime, datetime, datetime]] = field(default_factory=list)
    evaluation_episodes: dict[int, int | None] = field(default_factory=dict)

    async def upsert_markets(self, markets: Sequence[MarketInfo]) -> int:
        self.markets = list(markets)
        return len(markets)

    async def add_snapshots(self, captured_at: datetime, routes: Sequence[RouteQuote]) -> int:
        self.snapshots.extend(routes)
        return len(routes)

    async def add_evaluations(
        self,
        evaluations: Sequence[SpreadEvaluation],
        episode_ids: Sequence[int | None] | None = None,
    ) -> list[int]:
        ids = []
        links = list(episode_ids) if episode_ids is not None else [None] * len(evaluations)
        for evaluation, episode_id in zip(evaluations, links, strict=True):
            new_id = len(self.evaluations) + 1
            self.evaluations[new_id] = evaluation
            self.evaluation_episodes[new_id] = episode_id
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
        self,
        *,
        snapshots_before: datetime,
        evaluations_before: datetime,
        episodes_before: datetime,
    ) -> dict[str, int]:
        self.purged.append((snapshots_before, evaluations_before, episodes_before))
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
        self.contexts: list[AlertContext | None] = []

    async def dispatch_opportunity(
        self, evaluation_id: int, context: AlertContext | None = None
    ) -> None:
        self.contexts.append(context)
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


class MemoryEpisodes(IEpisodeRepository):
    """In-memory episode store with the same "never reopen a closed row" rule."""

    def __init__(self) -> None:
        self.rows: dict[int, OpportunityEpisode] = {}

    async def open(self, episode: OpportunityEpisode) -> OpportunityEpisode:
        assert episode.is_open
        for row in self.rows.values():
            if row.is_open and row.route_key == episode.route_key:
                return row
        new_id = len(self.rows) + 1
        self.rows[new_id] = replace(episode, id=new_id)
        return self.rows[new_id]

    async def set_survived_latency(self, episode_id: int, survived: bool) -> None:
        if self.rows[episode_id].is_open:
            self.rows[episode_id] = replace(self.rows[episode_id], survived_latency=survived)

    async def save(self, episodes: Sequence[OpportunityEpisode]) -> None:
        for episode in episodes:
            assert episode.id is not None
            if self.rows[episode.id].is_open:
                self.rows[episode.id] = episode

    async def list_open(self) -> list[OpportunityEpisode]:
        return [row for row in self.rows.values() if row.is_open]


class MemoryQuarantine(IQuarantineStore, IQuarantineRepository):
    """Quarantine store + history in memory; expiry follows the injected clock."""

    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
        self.entries: dict[str, RouteQuarantine] = {}
        self.history: list[RouteQuarantine] = []
        self.lifted: list[tuple[str, int]] = []

    async def add(self, quarantine: RouteQuarantine) -> bool:
        await self.active()
        if quarantine.route_key in self.entries:
            return False
        self.entries[quarantine.route_key] = quarantine
        return True

    async def active(self) -> dict[str, RouteQuarantine]:
        now = self.clock.now_ms()
        self.entries = {k: q for k, q in self.entries.items() if q.expires_at_ms > now}
        return dict(self.entries)

    async def lift(self, route_key: str) -> bool:
        return self.entries.pop(route_key, None) is not None

    async def record_start(self, quarantine: RouteQuarantine) -> None:
        self.history.append(quarantine)

    async def record_lift(self, route_key: str, at_ms: int) -> None:
        self.lifted.append((route_key, at_ms))


@dataclass
class PaperData:
    """Records of one shadow portfolio."""

    trades: list[tuple[TradeOutcome, int | None]] = field(default_factory=list)
    rebalances: dict[int, Rebalance] = field(default_factory=dict)
    snapshots: list[tuple[int, list[PaperHolding]]] = field(default_factory=list)


class MemoryPaper(IPaperRepository):
    """Paper records in memory (``commit`` keeps the same atomic shape as Postgres).

    ``trades`` / ``rebalances`` / ``snapshots`` are the primary portfolio (``all``); other
    shadow portfolios live in :attr:`data`.
    """

    def __init__(self) -> None:
        self.data: dict[str, PaperData] = {"all": PaperData()}
        self.fail_next = False
        self.fail_portfolios: set[str] = set()
        self.fail_cap_stats = False
        self._next_id = 1
        self._next_run_id = 0
        self.runs: dict[str, list[PortfolioRun]] = {}
        self.cap_stats: list[CapStatsDelta] = []

    @property
    def trades(self) -> list[tuple[TradeOutcome, int | None]]:
        return self.data["all"].trades

    @property
    def rebalances(self) -> dict[int, Rebalance]:
        return self.data["all"].rebalances

    @property
    def snapshots(self) -> list[tuple[int, list[PaperHolding]]]:
        return self.data["all"].snapshots

    async def commit(
        self,
        *,
        portfolio_id: str,
        at_ms: int,
        trades: Sequence[tuple[TradeOutcome, int | None]],
        rebalances: Sequence[Rebalance],
        holdings: Sequence[PaperHolding],
    ) -> list[Rebalance]:
        if self.fail_next or portfolio_id in self.fail_portfolios:
            self.fail_next = False
            raise ConnectionError("db down")
        data = self.data.setdefault(portfolio_id, PaperData())
        data.trades.extend(trades)
        stored = []
        for rebalance in rebalances:
            if rebalance.id is None:
                rebalance = replace(rebalance, id=self._next_id)
                self._next_id += 1
            data.rebalances[rebalance.id] = rebalance  # type: ignore[index]
            stored.append(rebalance)
        data.snapshots.append((at_ms, list(holdings)))
        return stored

    async def ensure_run(
        self, portfolio_id: str, definition: RunDefinition, now_ms: int
    ) -> PortfolioRun:
        runs = self.runs.setdefault(portfolio_id, [])
        if runs and runs[-1].definition.config_hash == definition.config_hash:
            return replace(runs[-1], created=False)
        self._next_run_id += 1
        previous = runs[-1].definition.config_hash if runs else None
        run = PortfolioRun(
            portfolio_id,
            self._next_run_id,
            now_ms,
            definition,
            created=True,
            previous_hash=previous,
        )
        runs.append(run)
        return run

    async def add_cap_stats(self, deltas: Sequence[CapStatsDelta]) -> None:
        if self.fail_cap_stats:
            raise ConnectionError("db down")
        self.cap_stats.extend(deltas)

    async def load_state(self, portfolio_id: str, since_ms: int = 0) -> PaperState | None:
        data = self.data.get(portfolio_id)
        if data is None:
            return None
        snapshots = [h for at, h in data.snapshots if at >= since_ms]
        if not snapshots:
            return None
        executed = [t for t, _ in data.trades if t.executed and t.at_ms >= since_ms]
        rebalances = [r for r in data.rebalances.values() if r.started_at_ms >= since_ms]
        return PaperState(
            holdings=snapshots[-1],
            in_flight=[r for r in rebalances if r.status is RebalanceStatus.IN_FLIGHT],
            realized=sum((t.net_usd for t in executed), D(0)),
            rebalance_costs=sum((r.fee_usd for r in rebalances), D(0)),
        )
