"""Exchange adapter registry (Open/Closed extension point)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from nexus.config.groups import ExchangeCredentials
from nexus.domain.errors import UnknownExchangeError
from nexus.interfaces.market_data import BaseExchangeAdapter


@dataclass(frozen=True, slots=True)
class AdapterOptions:
    """Exchange-agnostic adapter construction options."""

    timeout_ms: int = 10_000
    fallback_taker_fee: Decimal = Decimal("0.002")
    """Taker fee as a FRACTION (0.002 == 0.2 %) used when the exchange does not report one."""

    def __post_init__(self) -> None:
        if not Decimal(0) < self.fallback_taker_fee < Decimal("0.05"):
            msg = "fallback_taker_fee must be a fraction in (0, 0.05); did you pass a percent?"
            raise ValueError(msg)
        if self.timeout_ms <= 0:
            msg = "timeout_ms must be positive"
            raise ValueError(msg)

    @classmethod
    def from_settings(cls, *, timeout_ms: int, default_taker_fee_pct: Decimal) -> AdapterOptions:
        """Build from settings, converting the percent fee into a fraction."""
        return cls(timeout_ms=timeout_ms, fallback_taker_fee=default_taker_fee_pct / 100)


class AdapterFactory(Protocol):
    """Callable that builds an adapter from credentials and options."""

    def __call__(
        self, credentials: ExchangeCredentials, options: AdapterOptions
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
        self, name: str, credentials: ExchangeCredentials, options: AdapterOptions
    ) -> BaseExchangeAdapter:
        """Instantiate the adapter registered under ``name``."""
        try:
            factory = self._factories[name]
        except KeyError:
            msg = f"no adapter registered for exchange {name!r}; known: {self.names()}"
            raise UnknownExchangeError(msg) from None
        return factory(credentials, options)


exchange_registry = ExchangeRegistry()
"""Global registry populated by adapter modules on import (see ``nexus.adapters.cex``)."""
