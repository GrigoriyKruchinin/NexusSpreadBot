"""Exception hierarchy for the Nexus Spread Scanner."""

from __future__ import annotations


class NexusError(Exception):
    """Base class for all application errors."""


class ConfigurationError(NexusError):
    """Invalid or inconsistent configuration."""


class DataValidationError(NexusError):
    """External data failed validation."""


class InvalidOrderBookError(DataValidationError):
    """Order book is malformed (unsorted, crossed, non-positive levels)."""


class ExchangeError(NexusError):
    """Base class for exchange connectivity errors."""

    def __init__(self, exchange: str, message: str) -> None:
        super().__init__(f"[{exchange}] {message}")
        self.exchange = exchange


class ExchangeUnavailableError(ExchangeError):
    """Network failure, timeout or exchange maintenance (retryable)."""


class ExchangeRateLimitError(ExchangeError):
    """Rate limit hit (retryable after backoff)."""


class ExchangeAuthError(ExchangeError):
    """Invalid or insufficient API credentials (not retryable)."""


class ExchangeDataError(ExchangeError):
    """Exchange returned unusable data (e.g. unknown symbol)."""


class UnknownExchangeError(ConfigurationError):
    """Requested exchange has no registered adapter."""
