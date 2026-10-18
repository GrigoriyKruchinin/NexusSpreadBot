"""ccxt-compatible test double backed by recorded fixtures."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ccxt"


def load_fixture(exchange: str, name: str) -> Any:
    return json.loads((FIXTURES / exchange / f"{name}.json").read_text())


class FakeCcxtClient:
    def __init__(self, exchange: str, **overrides: Any) -> None:
        self.exchange = exchange
        self.has: dict[str, bool] = {
            "fetchCurrencies": True,
            "fetchTradingFees": False,
            "fetchDepositWithdrawFees": False,
        }
        self.has.update(overrides.pop("has", {}))
        self.payloads: dict[str, Any] = {
            "load_markets": load_fixture(exchange, "markets"),
            "fetch_tickers": load_fixture(exchange, "tickers"),
            "fetch_order_book": load_fixture(exchange, "order_book"),
            "fetch_currencies": load_fixture(exchange, "currencies"),
            "fetch_trading_fees": {},
            "fetch_deposit_withdraw_fees": {},
        }
        self.payloads.update(overrides)
        self.errors: dict[str, list[BaseException]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def fail(self, method: str, *errors: BaseException) -> None:
        self.errors.setdefault(method, []).extend(errors)

    async def _respond(self, method: str, *args: Any) -> Any:
        self.calls.append((method, args))
        queue = self.errors.get(method)
        if queue:
            raise queue.pop(0)
        payload = self.payloads[method]
        return payload(*args) if isinstance(payload, Callable) else payload  # type: ignore[arg-type]

    async def load_markets(self, reload: bool = False) -> Any:
        return await self._respond("load_markets", reload)

    async def fetch_tickers(self) -> Any:
        return await self._respond("fetch_tickers")

    async def fetch_order_book(self, symbol: str, limit: int) -> Any:
        return await self._respond("fetch_order_book", symbol, limit)

    async def watch_order_book(self, symbol: str, limit: int) -> Any:
        return await self._respond("fetch_order_book", symbol, limit)

    async def fetch_currencies(self) -> Any:
        return await self._respond("fetch_currencies")

    async def fetch_trading_fees(self) -> Any:
        return await self._respond("fetch_trading_fees")

    async def fetch_deposit_withdraw_fees(self) -> Any:
        return await self._respond("fetch_deposit_withdraw_fees")

    async def close(self) -> None:
        self.closed = True
