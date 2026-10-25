"""ccxt-compatible perp client double backed by recorded PUBLIC fixtures (no network)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ccxt

PERP_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "perp"


def load_perp_fixture(venue: str, name: str) -> Any:
    return json.loads((PERP_FIXTURES / venue / f"{name}.json").read_text())


class FakePerpClient:
    """Mimics the subset of the ccxt async client the perp adapters call."""

    apiKey = None  # noqa: N815 - ccxt attribute names
    secret = None
    password = None
    precisionMode = ccxt.TICK_SIZE  # noqa: N815

    def __init__(self, venue: str, **overrides: Any) -> None:
        self.venue = venue
        self.has: dict[str, bool] = {"fetchBidsAsks": True}
        self.payloads: dict[str, Any] = {}
        for name in (
            "markets",
            "tickers",
            "bids_asks",
            "mark_prices",
            "funding",
            "order_book",
            "klines",
            "funding_history",
            "funding_intervals",
            "tiers",
        ):
            try:
                self.payloads[name] = load_perp_fixture(venue, name)
            except FileNotFoundError:
                self.payloads[name] = None
        self.payloads.update(overrides)
        self.errors: dict[str, list[BaseException]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def fail(self, method: str, *errors: BaseException) -> None:
        self.errors.setdefault(method, []).extend(errors)

    def _respond(self, method: str, payload_name: str, *args: Any) -> Any:
        self.calls.append((method, args))
        queue = self.errors.get(method)
        if queue:
            raise queue.pop(0)
        payload = self.payloads[payload_name]
        return payload(*args) if isinstance(payload, Callable) else payload  # type: ignore[arg-type]

    async def load_markets(self, reload: bool = False) -> Any:
        return self._respond("load_markets", "markets", reload)

    async def fetch_tickers(self, symbols: Any = None) -> Any:
        return self._respond("fetch_tickers", "tickers")

    async def fetch_bids_asks(self, symbols: Any = None) -> Any:
        return self._respond("fetch_bids_asks", "bids_asks")

    async def fetch_mark_prices(self, symbols: Any = None) -> Any:
        return self._respond("fetch_mark_prices", "mark_prices")

    async def fetch_funding_rates(self, symbols: Any = None) -> Any:
        return self._respond("fetch_funding_rates", "funding")

    async def fetch_funding_rate(self, symbol: str) -> Any:
        return self._respond("fetch_funding_rate", "funding", symbol)[symbol]

    async def fetch_funding_intervals(self, symbols: Any = None) -> Any:
        return self._respond("fetch_funding_intervals", "funding_intervals")

    async def fetch_order_book(self, symbol: str, limit: int) -> Any:
        return self._respond("fetch_order_book", "order_book", symbol, limit)

    async def fetch_mark_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> Any:
        return self._respond("fetch_mark_ohlcv", "klines", symbol, timeframe, since, limit)

    async def fetch_funding_rate_history(self, symbol: str, since: int, limit: int) -> Any:
        return self._respond("fetch_funding_rate_history", "funding_history", symbol, since, limit)

    async def fetch_market_leverage_tiers(self, symbol: str) -> Any:
        return self._respond("fetch_market_leverage_tiers", "tiers", symbol)

    async def close(self) -> None:
        self.closed = True
