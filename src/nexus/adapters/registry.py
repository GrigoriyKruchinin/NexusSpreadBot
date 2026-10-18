"""Exchange adapter registry (Open/Closed extension point)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import UnknownExchangeError
from nexus.interfaces.market_data import BaseExchangeAdapter


class AdapterFactory(Protocol):
    """Callable that builds an adapter from credentials and a request timeout."""

    def __call__(
        self, credentials: ExchangeCredentials, *, timeout_ms: int
    ) -> BaseExchangeAdapter: ...


class ExchangeRegistry:
    """Maps exchange names to adapter factories."""

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    def register(self, name: str) -> Callable[[AdapterFactory], AdapterFactory]:
        """Decorator registering an adapter class/factory under ``name``."""

        def decorator(factory: AdapterFactory) -> AdapterFactory:
            if name in self._factories:
                msg = f"exchange adapter already registered: {name}"
                raise ValueError(msg)
            self._factories[name] = factory
            return factory

        return decorator

    def names(self) -> tuple[str, ...]:
        """Registered exchange names (sorted)."""
        return tuple(sorted(self._factories))

    def create(
        self, name: str, credentials: ExchangeCredentials, *, timeout_ms: int
    ) -> BaseExchangeAdapter:
        """Instantiate the adapter registered under ``name``."""
        try:
            factory = self._factories[name]
        except KeyError:
            msg = f"no adapter registered for exchange {name!r}; known: {self.names()}"
            raise UnknownExchangeError(msg) from None
        return factory(credentials, timeout_ms=timeout_ms)


exchange_registry = ExchangeRegistry()
"""Global registry populated by adapter modules on import."""
