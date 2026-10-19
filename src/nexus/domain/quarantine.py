"""Route quarantine: dead routes (spread that cannot be closed) are excluded for a while."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QuarantineReason(StrEnum):
    """Why a route was quarantined."""

    UNVERIFIED_PERSISTENT = "unverified_persistent"
    """An episode stayed open too long without a verified transfer path (ZIL/ONE pattern)."""
    TRANSFER_UNAVAILABLE = "transfer_unavailable"
    """The asset cannot be withdrawn on the buy venue / deposited on the sell venue."""


def route_key(symbol: str, buy_exchange: str, sell_exchange: str) -> str:
    """Same format as ``SpreadEvaluation.route_key`` / ``OpportunityEpisode.route_key``."""
    return f"{symbol}|{buy_exchange}>{sell_exchange}"


@dataclass(frozen=True, slots=True)
class RouteQuarantine:
    """An active quarantine of one directed route."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    reason: QuarantineReason
    started_at_ms: int
    expires_at_ms: int
    note: str = ""

    def __post_init__(self) -> None:
        if self.expires_at_ms <= self.started_at_ms:
            msg = "a quarantine must expire after it starts"
            raise ValueError(msg)

    @property
    def route_key(self) -> str:
        """Route identifier."""
        return route_key(self.symbol, self.buy_exchange, self.sell_exchange)

    @property
    def ttl_ms(self) -> int:
        """Configured duration."""
        return self.expires_at_ms - self.started_at_ms
