"""System events exchanged between services (JSON-serializable payloads).

The scanner never holds the Telegram token: it publishes these events to the alerts queue,
where the notifier renders and delivers them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, ClassVar, Literal

EventKind = Literal["scanner_started", "scanner_stopped", "exchange_down", "exchange_recovered"]


@dataclass(frozen=True, slots=True)
class ExchangeStatus:
    """Exchange connectivity summary for the startup message."""

    name: str
    authenticated: bool
    markets: int


@dataclass(frozen=True, slots=True)
class ScannerStarted:
    """Scanner process started."""

    kind: ClassVar[EventKind] = "scanner_started"
    exchanges: tuple[ExchangeStatus, ...]
    min_net_profit_pct: str
    min_net_profit_usd: str
    reference_notional_usd: str
    common_symbols: int


@dataclass(frozen=True, slots=True)
class ScannerStopped:
    """Scanner process stopped gracefully."""

    kind: ClassVar[EventKind] = "scanner_stopped"
    reason: str = "shutdown"


@dataclass(frozen=True, slots=True)
class ExchangeDown:
    """Exchange became unreachable for consecutive sweeps."""

    kind: ClassVar[EventKind] = "exchange_down"
    exchange: str
    error: str
    consecutive_failures: int


@dataclass(frozen=True, slots=True)
class ExchangeRecovered:
    """Exchange is reachable again."""

    kind: ClassVar[EventKind] = "exchange_recovered"
    exchange: str
    downtime_s: int


SystemEvent = ScannerStarted | ScannerStopped | ExchangeDown | ExchangeRecovered

_EVENT_TYPES: dict[str, type[Any]] = {
    cls.kind: cls for cls in (ScannerStarted, ScannerStopped, ExchangeDown, ExchangeRecovered)
}


def event_to_payload(event: SystemEvent) -> dict[str, Any]:
    """Serialize an event into a JSON-safe dict (for Celery)."""
    return {"kind": event.kind, "data": asdict(event)}


def event_from_payload(payload: dict[str, Any]) -> SystemEvent:
    """Inverse of :func:`event_to_payload`; raises ``ValueError`` for unknown kinds."""
    kind = payload.get("kind")
    cls = _EVENT_TYPES.get(str(kind))
    if cls is None:
        msg = f"unknown system event kind: {kind!r}"
        raise ValueError(msg)
    data = dict(payload.get("data") or {})
    if cls is ScannerStarted:
        data["exchanges"] = tuple(ExchangeStatus(**e) for e in data.get("exchanges", ()))
    event: SystemEvent = cls(**data)
    return event


def decimal_str(value: Decimal) -> str:
    """Stable string form of a Decimal for event payloads."""
    return format(value.normalize(), "f")


__all__ = [
    "ExchangeDown",
    "ExchangeRecovered",
    "ExchangeStatus",
    "ScannerStarted",
    "ScannerStopped",
    "SystemEvent",
    "decimal_str",
    "event_from_payload",
    "event_to_payload",
]
