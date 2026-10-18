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


class ReadOnlyViolationError(NexusError):
    """A non-read-only exchange request was attempted and blocked (safety guard)."""


class UnknownExchangeError(ConfigurationError):
    """Requested exchange has no registered adapter."""


class NotificationError(NexusError):
    """Notification delivery failed (retryable unless stated otherwise)."""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class NotificationRejectedError(NotificationError):
    """The channel rejected the message permanently (bad request, chat not found, blocked)."""
