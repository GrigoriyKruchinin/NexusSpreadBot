"""System events exchanged between services (JSON-serializable payloads).

The scanner never holds the Telegram token: it publishes these events to the alerts queue,
where the notifier renders and delivers them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, ClassVar, Literal

EventKind = Literal[
    "scanner_started",
    "scanner_stopped",
    "exchange_down",
    "exchange_recovered",
    "episode_closed",
    "routes_quarantined",
    "watchdog_alert",
    "watchdog_recovered",
    "watchdog_retired",
]


@dataclass(frozen=True, slots=True)
class ExchangeStatus:
    """Exchange connectivity summary for the startup message."""

    name: str
    authenticated: bool
    markets: int
    transfer_coverage_pct: int | None = None
    """Scanned assets with a known deposit/withdrawal status (%); ``None`` if not measured."""


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


@dataclass(frozen=True, slots=True)
class EpisodeClosed:
    """An alerted opportunity episode ended."""

    kind: ClassVar[EventKind] = "episode_closed"
    symbol: str
    buy_exchange: str
    sell_exchange: str
    reason: str
    duration_s: int
    peak_net_usd: str
    peak_net_pct: str
    evaluations: int
    realerts: int
    survived_latency: bool | None


@dataclass(frozen=True, slots=True)
class QuarantinedRoute:
    """One newly quarantined route (part of :class:`RoutesQuarantined`)."""

    symbol: str
    buy_exchange: str
    sell_exchange: str
    reason: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class RoutesQuarantined:
    """Routes quarantined in one sweep (one message, not one per route)."""

    kind: ClassVar[EventKind] = "routes_quarantined"
    routes: tuple[QuarantinedRoute, ...]
    duration_h: int


@dataclass(frozen=True, slots=True)
class WatchdogAlert:
    """A liveness check failed (once per incident). Carries codes and numbers only."""

    kind: ClassVar[EventKind] = "watchdog_alert"
    check: str
    """``scanner`` or ``backup``."""
    reason: str
    """Reason code, rendered to Russian text by the notifier."""
    minutes: int | None = None
    """Age of the last sign of life / last backup, in minutes (``None`` = unknown)."""


@dataclass(frozen=True, slots=True)
class WatchdogRecovered:
    """The failed check is healthy again (sent once after a :class:`WatchdogAlert`)."""

    kind: ClassVar[EventKind] = "watchdog_recovered"
    check: str
    downtime_min: int


@dataclass(frozen=True, slots=True)
class WatchdogRetired:
    """A firing paper set was silent so long that it is considered removed from the config.

    Not a recovery: the set never came back. Sent once, then the incident state is cleared.
    """

    kind: ClassVar[EventKind] = "watchdog_retired"
    check: str
    hours: int
    """The retire threshold (hours without data)."""


SystemEvent = (
    ScannerStarted
    | ScannerStopped
    | ExchangeDown
    | ExchangeRecovered
    | EpisodeClosed
    | RoutesQuarantined
    | WatchdogAlert
    | WatchdogRecovered
    | WatchdogRetired
)

_EVENT_TYPES: dict[str, type[Any]] = {
    cls.kind: cls
    for cls in (
        ScannerStarted,
        ScannerStopped,
        ExchangeDown,
        ExchangeRecovered,
        EpisodeClosed,
        RoutesQuarantined,
        WatchdogAlert,
        WatchdogRecovered,
        WatchdogRetired,
    )
}


@dataclass(frozen=True, slots=True)
class AlertContext:
    """Episode context of an opportunity alert (travels with the alert task)."""

    episode_id: int | None = None
    realert: int = 0
    """0 for the episode's first alert, n for its n-th re-alert."""
    previous_net_usd: str | None = None
    """Net profit of the previous alert of the episode (re-alerts only)."""

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> AlertContext:
        """Inverse of :meth:`to_payload`; ``None`` (old tasks) means no context."""
        if not payload:
            return cls()
        return cls(
            episode_id=payload.get("episode_id"),
            realert=int(payload.get("realert") or 0),
            previous_net_usd=payload.get("previous_net_usd"),
        )


def event_to_payload(event: SystemEvent, *, emitted_at_ms: int | None = None) -> dict[str, Any]:
    """Serialize an event into a JSON-safe dict (for Celery).

    ``emitted_at_ms`` lets the consumer drop events that sat in the queue for too long.
    """
    payload: dict[str, Any] = {"kind": event.kind, "data": asdict(event)}
    if emitted_at_ms is not None:
        payload["emitted_at_ms"] = emitted_at_ms
    return payload


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
    if cls is RoutesQuarantined:
        data["routes"] = tuple(QuarantinedRoute(**r) for r in data.get("routes", ()))
    event: SystemEvent = cls(**data)
    return event


def decimal_str(value: Decimal) -> str:
    """Stable string form of a Decimal for event payloads."""
    return format(value.normalize(), "f")


__all__ = [
    "AlertContext",
    "EpisodeClosed",
    "ExchangeDown",
    "ExchangeRecovered",
    "ExchangeStatus",
    "QuarantinedRoute",
    "RoutesQuarantined",
    "ScannerStarted",
    "ScannerStopped",
    "SystemEvent",
    "WatchdogAlert",
    "WatchdogRecovered",
    "WatchdogRetired",
    "decimal_str",
    "event_from_payload",
    "event_to_payload",
]
