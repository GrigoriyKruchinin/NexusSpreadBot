"""Perp adapter registry.

Separate from the spot :data:`~nexus.adapters.registry.exchange_registry` on purpose (ADR 0009):
perp adapters take **no credentials**, so the factory signature cannot even receive a key.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from nexus.adapters.registry import AdapterOptions
from nexus.domain.errors import UnknownExchangeError
from nexus.interfaces.perp import IPerpMarketData


class PerpAdapterFactory(Protocol):
    """Callable that builds a credential-less perp adapter."""

    def __call__(self, options: AdapterOptions) -> IPerpMarketData: ...


class PerpRegistry:
    """Maps venue names to perp adapter factories."""

    def __init__(self) -> None:
        self._factories: dict[str, PerpAdapterFactory] = {}

    def register(self, name: str) -> Callable[[PerpAdapterFactory], PerpAdapterFactory]:
        """Decorator registering an adapter class/factory under ``name``."""

        def decorator(factory: PerpAdapterFactory) -> PerpAdapterFactory:
            if name in self._factories:
                msg = f"perp adapter already registered: {name}"
                raise ValueError(msg)
            self._factories[name] = factory
            return factory

        return decorator

    def names(self) -> tuple[str, ...]:
        """Registered venue names (sorted)."""
        return tuple(sorted(self._factories))

    def create(self, name: str, options: AdapterOptions) -> IPerpMarketData:
        """Instantiate the perp adapter registered under ``name``."""
        try:
            factory = self._factories[name]
        except KeyError:
            msg = f"no perp adapter registered for {name!r}; known: {self.names()}"
            raise UnknownExchangeError(msg) from None
        return factory(options)


perp_registry = PerpRegistry()
"""Global registry populated by perp adapter modules on import (see ``nexus.adapters.perp``)."""
