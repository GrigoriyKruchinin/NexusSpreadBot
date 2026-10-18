from collections.abc import Mapping, Sequence

import pytest

from nexus.adapters.registry import AdapterOptions, ExchangeRegistry
from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import UnknownExchangeError
from nexus.domain.models import AssetTransferInfo, MarketInfo, OrderBook, Ticker
from nexus.interfaces.market_data import BaseExchangeAdapter


class _Dummy(BaseExchangeAdapter):
    name = "dummy"

    def __init__(self, credentials: ExchangeCredentials, options: AdapterOptions) -> None:
        self.timeout_ms = options.timeout_ms
        self.closed = False

    async def fetch_tickers(self, symbols: Sequence[str]) -> Mapping[str, Ticker]:
        return {}

    async def fetch_order_book(self, symbol: str, depth: int) -> OrderBook:
        raise NotImplementedError

    async def load_markets(self) -> Sequence[MarketInfo]:
        return ()

    async def load_transfer_info(self) -> Mapping[str, AssetTransferInfo] | None:
        return None

    async def close(self) -> None:
        self.closed = True


def test_register_and_create() -> None:
    registry = ExchangeRegistry()
    registry.register("dummy")(_Dummy)
    adapter = registry.create("dummy", ExchangeCredentials(), AdapterOptions(timeout_ms=5_000))
    assert isinstance(adapter, _Dummy)
    assert adapter.timeout_ms == 5_000
    assert registry.names() == ("dummy",)


def test_duplicate_registration_rejected() -> None:
    registry = ExchangeRegistry()
    registry.register("dummy")(_Dummy)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("dummy")(_Dummy)


def test_unknown_exchange() -> None:
    with pytest.raises(UnknownExchangeError):
        ExchangeRegistry().create("nope", ExchangeCredentials(), AdapterOptions())


async def test_adapter_context_manager_closes() -> None:
    async with _Dummy(ExchangeCredentials(), AdapterOptions()) as adapter:
        assert not adapter.closed
    assert adapter.closed
