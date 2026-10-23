"""Cheap ticker-based pre-filter selecting routes worth a full depth evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from nexus.domain.models import ZERO, MarketInfo, Ticker
from nexus.domain.quarantine import route_key

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class RouteQuote:
    """Top-of-book view of one route: buy at ``ask`` on one venue, sell at ``bid`` on another."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    ask: Decimal
    bid: Decimal
    gross_spread_pct: Decimal
    fee_bound_net_pct: Decimal
    """Gross spread minus both taker fees: an upper bound of the achievable net spread."""


@dataclass(frozen=True, slots=True)
class CandidateFilter:
    """Thresholds of the pre-filter."""

    min_net_profit_pct: Decimal
    max_gross_spread_pct: Decimal
    min_quote_volume_usd: Decimal


@dataclass(frozen=True, slots=True)
class SetSelection:
    """Union of the per-set top-N candidates and which sets each route is a candidate of."""

    routes: list[RouteQuote]
    """Ranked like :meth:`CandidateFinder.select` (best fee-bound net first), no duplicates."""
    membership: dict[str, frozenset[str]]
    """``route_key -> names of the venue sets whose own top-N contains the route``."""


class CandidateFinder:
    """Ranks all cross-exchange routes by top-of-book spread and selects candidates."""

    def __init__(self, config: CandidateFilter) -> None:
        self._config = config

    def rank_routes(
        self,
        tickers: Mapping[str, Mapping[str, Ticker]],
        markets: Mapping[str, Mapping[str, MarketInfo]],
    ) -> list[RouteQuote]:
        """Return every route with a positive gross spread, best first.

        ``tickers`` and ``markets`` are keyed by exchange, then by unified symbol.
        """
        by_symbol: dict[str, list[tuple[str, Ticker, MarketInfo]]] = defaultdict(list)
        for exchange, exchange_tickers in tickers.items():
            exchange_markets = markets.get(exchange, {})
            for symbol, ticker in exchange_tickers.items():
                market = exchange_markets.get(symbol)
                if market is None or not market.active or not self._liquid(ticker):
                    continue
                by_symbol[symbol].append((exchange, ticker, market))

        routes: list[RouteQuote] = []
        for symbol, venues in by_symbol.items():
            if len(venues) < 2:  # a route needs two venues
                continue
            for buy_ex, buy_ticker, buy_market in venues:
                ask = buy_ticker.ask
                if ask is None or ask <= ZERO:
                    continue
                for sell_ex, sell_ticker, sell_market in venues:
                    bid = sell_ticker.bid
                    if sell_ex == buy_ex or bid is None or bid <= ask:
                        continue
                    gross = (bid - ask) / ask * HUNDRED
                    fees_pct = (buy_market.taker_fee + sell_market.taker_fee) * HUNDRED
                    routes.append(
                        RouteQuote(
                            symbol=symbol,
                            buy_exchange=buy_ex,
                            sell_exchange=sell_ex,
                            ask=ask,
                            bid=bid,
                            gross_spread_pct=gross,
                            fee_bound_net_pct=gross - fees_pct,
                        )
                    )
        routes.sort(key=lambda r: (-r.gross_spread_pct, r.symbol, r.buy_exchange, r.sell_exchange))
        return routes

    def select(self, routes: list[RouteQuote], limit: int) -> list[RouteQuote]:
        """Pick up to ``limit`` routes that could still clear the net threshold."""
        cfg = self._config
        selected = [
            r
            for r in routes
            if r.fee_bound_net_pct >= cfg.min_net_profit_pct
            and r.gross_spread_pct <= cfg.max_gross_spread_pct
        ]
        selected.sort(key=lambda r: (-r.fee_bound_net_pct, r.symbol))
        return selected[:limit]

    def select_per_set(
        self, routes: list[RouteQuote], limit: int, sets: Mapping[str, frozenset[str]]
    ) -> SetSelection:
        """Apply the top-N cap separately inside every venue set.

        A route belongs to a set only if BOTH legs are in the set; the cap is applied after
        that restriction, so a route crowded out of ``all`` by conditional-venue routes still
        competes in ``excl_conditional`` (no crowd-out bias). The evaluation list is the union.
        """
        members: dict[str, set[str]] = defaultdict(set)
        by_key: dict[str, RouteQuote] = {}
        for name, venues in sets.items():
            inside = [r for r in routes if r.buy_exchange in venues and r.sell_exchange in venues]
            for route in self.select(inside, limit):
                key = route_key(route.symbol, route.buy_exchange, route.sell_exchange)
                by_key[key] = route
                members[key].add(name)
        union = sorted(by_key.values(), key=lambda r: (-r.fee_bound_net_pct, r.symbol))
        return SetSelection(union, {k: frozenset(v) for k, v in members.items()})

    def _liquid(self, ticker: Ticker) -> bool:
        threshold = self._config.min_quote_volume_usd
        if threshold <= ZERO:
            return True
        return ticker.quote_volume_24h is not None and ticker.quote_volume_24h >= threshold
