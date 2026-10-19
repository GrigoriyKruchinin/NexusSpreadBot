"""Paper trading orchestration: prices, trades on alerts, virtual rebalancing, persistence.

Read-only by construction: it only consumes order books / metadata the scanner already
fetched and writes simulation records. It has no exchange client and moves nothing.
"""

from __future__ import annotations

import asyncio
import copy
import statistics
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal

import structlog

from nexus.domain.clock import Clock
from nexus.domain.models import ZERO, MarketInfo, OrderBook, Ticker
from nexus.domain.quarantine import route_key
from nexus.domain.spread import SpreadBreakdown, TransferQuote
from nexus.engine.estimator import NetSpreadEstimator
from nexus.interfaces.repositories import IPaperRepository, PaperHolding
from nexus.simulation.portfolio import (
    USD_QUOTE,
    PaperConfig,
    PaperPortfolio,
    Rebalance,
    RebalanceStatus,
    SkipReason,
    TradeOutcome,
)

log = structlog.get_logger(__name__)

SNAPSHOT_INTERVAL_MS = 15 * 60_000
"""Balances are snapshotted after every change and at least this often (mark-to-market)."""
ROUTE_TRADE_COOLDOWN_MS = 60_000
"""A route is paper-traded at most once per minute: a quick re-alert must not capture the
same order book depth twice (paper fills never consume real liquidity)."""
MAX_TICKER_SPREAD = Decimal("0.05")
"""Tickers with a crossed or wider than 5 % top of book are ignored for paper prices."""

NetworkQuoter = Callable[[str, str, str], TransferQuote]
"""``(asset, from_exchange, to_exchange) -> cheapest transfer path`` from read-only metadata."""


class PaperTrader:
    """Runs the :class:`PaperPortfolio` against live scanner data."""

    def __init__(
        self,
        config: PaperConfig,
        repository: IPaperRepository,
        estimator: NetSpreadEstimator,
        clock: Clock,
    ) -> None:
        """``estimator`` prices trades: trade notional, no per-trade transfer cost."""
        if estimator.config.include_transfer_cost:
            msg = "paper estimator must not charge transfer costs per trade (rebalancing does)"
            raise ValueError(msg)
        self._config = config
        self._repo = repository
        self._estimator = estimator
        self._clock = clock
        self.portfolio = PaperPortfolio(config)
        self._last_snapshot_ms: int | None = None
        self._last_trade_ms: dict[str, int] = {}
        self._lock = asyncio.Lock()
        """Serializes state changes + commits of background trades and the sweep."""

    async def start(self) -> None:
        """Resume the portfolio from the last persisted state, if any."""
        state = await self._repo.load_state()
        if state is None:
            return
        self.portfolio = PaperPortfolio.restore(
            self._config,
            [(h.exchange, h.asset, h.amount, h.seed) for h in state.holdings],
            state.in_flight,
            {"realized": state.realized, "rebalance_costs": state.rebalance_costs},
        )
        for holding in state.holdings:
            if holding.price_usd is not None and holding.asset != USD_QUOTE:
                self.portfolio.mark_price(holding.asset, holding.price_usd)
        log.info(
            "paper_resumed",
            venues=len(state.holdings),
            in_flight=len(state.in_flight),
            realized=str(state.realized),
        )

    def mark_prices(
        self,
        tickers: Mapping[str, Mapping[str, Ticker]],
        markets: Mapping[str, Mapping[str, MarketInfo]],
    ) -> None:
        """Median top-of-book mid per base asset across exchanges (USD-stable quotes)."""
        mids: dict[str, list[Decimal]] = {}
        for exchange, by_symbol in tickers.items():
            exchange_markets = markets.get(exchange, {})
            for symbol, ticker in by_symbol.items():
                market = exchange_markets.get(symbol)
                if market is None or ticker.bid is None or ticker.ask is None:
                    continue
                if not ZERO < ticker.bid <= ticker.ask <= ticker.bid * (1 + MAX_TICKER_SPREAD):
                    continue  # crossed / broken / illiquid top of book
                mids.setdefault(market.base, []).append((ticker.bid + ticker.ask) / 2)
        for asset, values in mids.items():
            self.portfolio.mark_price(asset, Decimal(statistics.median(values)))

    async def execute(
        self,
        *,
        episode_id: int | None,
        symbol: str,
        base: str,
        buy_book: OrderBook | None,
        sell_book: OrderBook | None,
        buy_market: MarketInfo | None,
        sell_market: MarketInfo | None,
        transfer: TransferQuote,
        network_quote: NetworkQuoter,
    ) -> TradeOutcome:
        """Simulate the trade on the books taken after the latency (sized to the available
        inventory), then rebalance if a balance fell below the threshold."""
        async with self._lock:
            before = copy.deepcopy(self.portfolio)
            now = self._tick()
            outcome = self._simulate(
                symbol, base, buy_book, sell_book, buy_market, sell_market, transfer, now
            )
            rebalances = self._rebalance(now, network_quote)
            changed = outcome.executed or bool(rebalances)
            try:
                await self._commit(now, [(outcome, episode_id)], rebalances, snapshot=changed)
            except Exception:
                self.portfolio = before  # memory never runs ahead of the database
                raise
            if outcome.executed:
                self._last_trade_ms[_route(outcome)] = now
        log.info(
            "paper_trade",
            route=_route(outcome),
            executed=outcome.executed,
            skip_reason=outcome.skip_reason.value if outcome.skip_reason else None,
            net_usd=str(outcome.net_usd),
            episode_id=episode_id,
        )
        return outcome

    def _simulate(
        self,
        symbol: str,
        base: str,
        buy_book: OrderBook | None,
        sell_book: OrderBook | None,
        buy_market: MarketInfo | None,
        sell_market: MarketInfo | None,
        transfer: TransferQuote,
        now: int,
    ) -> TradeOutcome:
        buy_exchange = buy_market.exchange if buy_market else ""
        sell_exchange = sell_market.exchange if sell_market else ""

        def skipped(reason: SkipReason) -> TradeOutcome:
            return TradeOutcome(symbol, base, buy_exchange, sell_exchange, now, reason)

        key = route_key(symbol, buy_exchange, sell_exchange)
        if now - self._last_trade_ms.get(key, -ROUTE_TRADE_COOLDOWN_MS) < ROUTE_TRADE_COOLDOWN_MS:
            return skipped(SkipReason.RECENT_FILL)
        if (
            buy_book is None
            or sell_book is None
            or buy_market is None
            or sell_market is None
            or buy_book.best_ask is None
        ):
            return skipped(SkipReason.BOOKS_UNAVAILABLE)
        size, reason = self.portfolio.trade_size(
            buy_exchange, sell_exchange, base, buy_book.best_ask
        )
        if reason is not None:
            return skipped(reason)
        breakdown = self._price(size, buy_book, sell_book, buy_market, sell_market, transfer)
        if breakdown is None:
            return skipped(SkipReason.UNFILLABLE)
        return self.portfolio.trade(symbol, base, buy_exchange, sell_exchange, breakdown, now)

    def _price(
        self,
        size_usd: Decimal,
        buy_book: OrderBook,
        sell_book: OrderBook,
        buy_market: MarketInfo,
        sell_market: MarketInfo,
        transfer: TransferQuote,
    ) -> SpreadBreakdown | None:
        """Depth-walked fill for ``size_usd`` with the scanner's fees and lot rounding."""
        config = replace(self._estimator.config, reference_notional_usd=size_usd)
        try:
            evaluation = NetSpreadEstimator(config, self._clock).evaluate(
                buy_book=buy_book,
                sell_book=sell_book,
                buy_market=buy_market,
                sell_market=sell_market,
                transfer=transfer,
            )
        except (ValueError, ArithmeticError):
            log.exception("paper_pricing_failed", symbol=buy_book.symbol)
            return None
        return evaluation.breakdown

    async def on_sweep(self, network_quote: NetworkQuoter) -> None:
        """Settle arrived transfers, start due rebalances, snapshot periodically."""
        async with self._lock:
            before = copy.deepcopy(self.portfolio)
            now = self._tick()
            changes = [*self.portfolio.settle(now), *self._rebalance(now, network_quote)]
            due = (
                self._last_snapshot_ms is None
                or now - self._last_snapshot_ms >= SNAPSHOT_INTERVAL_MS
            )
            if not changes and not (due and self.portfolio.seeds):
                return
            try:
                await self._commit(now, [], changes, snapshot=True)
            except Exception:
                self.portfolio = before
                raise

    def _tick(self) -> int:
        """Strictly increasing commit time: the latest snapshot set is always unambiguous."""
        now = self._clock.now_ms()
        if self._last_snapshot_ms is not None and now <= self._last_snapshot_ms:
            now = self._last_snapshot_ms + 1
        return now

    def _rebalance(self, now: int, network_quote: NetworkQuoter) -> list[Rebalance]:
        started: list[Rebalance] = []
        for need in self.portfolio.rebalance_needs(now):
            quote = network_quote(need.asset, need.from_exchange, need.to_exchange)
            rebalance = self.portfolio.start_rebalance(need, quote, now)
            started.append(rebalance)
            log.info(
                "paper_rebalance",
                asset=need.asset,
                route=f"{need.from_exchange}>{need.to_exchange}",
                amount=str(need.amount),
                status=rebalance.status.value,
                fee_usd=str(rebalance.fee_usd),
                network=rebalance.network,
            )
        return started

    async def _commit(
        self,
        now: int,
        trades: list[tuple[TradeOutcome, int | None]],
        rebalances: list[Rebalance],
        *,
        snapshot: bool,
    ) -> None:
        holdings = (
            []
            if not snapshot
            else [
                PaperHolding(
                    exchange=exchange,
                    asset=asset,
                    amount=amount,
                    seed=self.portfolio.seeds.get((exchange, asset)),
                    price_usd=Decimal(1)
                    if asset == USD_QUOTE
                    else self.portfolio.prices.get(asset),
                )
                for (exchange, asset), amount in sorted(self.portfolio.balances.items())
            ]
        )
        stored = await self._repo.commit(
            at_ms=now, trades=trades, rebalances=rebalances, holdings=holdings
        )
        # Remember database ids of transfers still in flight (needed to mark them completed).
        ids = {self._identity(r): r.id for r in stored if r.status is RebalanceStatus.IN_FLIGHT}
        self.portfolio.in_flight = [
            replace(r, id=ids.get(self._identity(r), r.id)) for r in self.portfolio.in_flight
        ]
        if snapshot:
            self._last_snapshot_ms = now

    @staticmethod
    def _identity(r: Rebalance) -> tuple[str, str, str, int]:
        return (r.asset, r.from_exchange, r.to_exchange, r.started_at_ms)


def _route(outcome: TradeOutcome) -> str:
    return route_key(outcome.symbol, outcome.buy_exchange, outcome.sell_exchange)
