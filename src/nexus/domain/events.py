"""System events exchanged between services (JSON-serializable payloads).

The scanner never holds the Telegram token: it publishes these events to the alerts queue,
where the notifier renders and delivers them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, Literal

from nexus.domain.episodes import OpportunityEpisode
from nexus.domain.spread import SpreadEvaluation, TransferStatus

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
    ip_unbound_venues: tuple[str, ...] = ()
    """Venues whose keys have no IP binding (local-run waiver); names only."""


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


SystemEvent = (
    ScannerStarted
    | ScannerStopped
    | ExchangeDown
    | ExchangeRecovered
    | EpisodeClosed
    | RoutesQuarantined
    | WatchdogAlert
    | WatchdogRecovered
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
    )
}


ALERT_PAYLOAD_VERSION = 2
"""Version ``v`` of the alert task payload. 1 = episode context only (rows queued before the
alert data model), 2 = adds volume, transfer and lifetime. Decoding accepts any version."""

_BASE_DP = Decimal("0.00000001")
_USD_DP = Decimal("0.01")
_FEE_USD_DP = Decimal("0.0001")


def _q(value: Decimal | None, places: Decimal) -> str | None:
    """Rounded (half up) stable string of a Decimal; ``None`` stays ``None``."""
    if value is None:
        return None
    return decimal_str(value.quantize(places, rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class AlertVolume:
    """Executable volume from the order books (Decimals as strings, USD == quote)."""

    scanned_base: str
    scanned_quote: str
    """Volume the scanner priced (the reference notional)."""
    max_base: str
    max_quote: str
    max_net_usd: str
    """Largest volume that is still net-positive, and the net profit at that volume."""


@dataclass(frozen=True, slots=True)
class AlertTransfer:
    """Transfer block of an alert. ``unknown`` is explicit, never replaced by a guess."""

    status: str
    """``verified`` | ``unknown`` | ``unavailable`` (TransferStatus)."""
    network: str | None = None
    fee_base: str | None = None
    fee_usd: str | None = None
    """Withdrawal fee in the coin and in USD; ``None`` unless the transfer is verified."""
    est_arrival_min: str | None = None
    arrival_source: str | None = None
    """``exchange`` | ``table``; the time is an estimate either way."""
    withdraw: str = "unknown"
    deposit: str = "unknown"
    """``open`` | ``closed`` | ``unknown`` for the source / destination venue."""
    withdraw_min: str | None = None
    deposit_min: str | None = None
    deposit_confirmations: int | None = None
    busy: bool | None = None
    contract_verified: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class AlertLifetime:
    """Episode times (epoch ms) behind the 'lifetime' line of an alert."""

    opened_at_ms: int
    last_seen_at_ms: int
    closed_at_ms: int | None = None

    def lifetime_ms(self, now_ms: int | None = None) -> int:
        """Open episode: until the last qualifying evaluation; closed: until the close."""
        end = self.closed_at_ms if self.closed_at_ms is not None else self.last_seen_at_ms
        if now_ms is not None and self.closed_at_ms is None:
            end = max(end, now_ms)
        return max(0, end - self.opened_at_ms)


def _volume_payload(evaluation: SpreadEvaluation) -> AlertVolume | None:
    volume = evaluation.volume
    if volume is None:
        return None
    return AlertVolume(
        scanned_base=_q(volume.scanned_base, _BASE_DP) or "0",
        scanned_quote=_q(volume.scanned_quote, _USD_DP) or "0",
        max_base=_q(volume.max_base, _BASE_DP) or "0",
        max_quote=_q(volume.max_quote, _USD_DP) or "0",
        max_net_usd=_q(volume.max_net_usd, _USD_DP) or "0",
    )


def _transfer_payload(evaluation: SpreadEvaluation) -> AlertTransfer:
    quote = evaluation.transfer
    verified = quote.status is TransferStatus.VERIFIED
    fee_usd: Decimal | None = None
    if verified and evaluation.breakdown is not None:
        fee_usd = quote.fee_base * evaluation.breakdown.vwap_sell
    return AlertTransfer(
        status=quote.status.value,
        network=quote.network,
        fee_base=_q(quote.fee_base, _BASE_DP) if verified else None,
        fee_usd=_q(fee_usd, _FEE_USD_DP),
        est_arrival_min=_q(quote.est_arrival_min, Decimal("0.1")),
        arrival_source=quote.arrival_source,
        withdraw=quote.withdraw_state.value,
        deposit=quote.deposit_state.value,
        withdraw_min=_q(quote.withdraw_min, _BASE_DP),
        deposit_min=_q(quote.deposit_min, _BASE_DP),
        deposit_confirmations=quote.deposit_confirmations,
        busy=quote.busy,
        contract_verified=quote.contract_verified,
        note=quote.note,
    )


def _lifetime_payload(episode: OpportunityEpisode | None) -> AlertLifetime | None:
    if episode is None:
        return None
    return AlertLifetime(episode.opened_at_ms, episode.last_seen_at_ms, episode.closed_at_ms)


@dataclass(frozen=True, slots=True)
class AlertContext:
    """Episode context and alert data of an opportunity alert (travels with the alert task)."""

    episode_id: int | None = None
    realert: int = 0
    """0 for the episode's first alert, n for its n-th re-alert."""
    previous_net_usd: str | None = None
    """Net profit of the previous alert of the episode (re-alerts only)."""
    volume: AlertVolume | None = None
    transfer: AlertTransfer | None = None
    lifetime: AlertLifetime | None = None
    v: int = ALERT_PAYLOAD_VERSION

    @classmethod
    def build(
        cls,
        evaluation: SpreadEvaluation,
        episode: OpportunityEpisode | None,
        *,
        realert: int = 0,
        previous_net_usd: Decimal | None = None,
    ) -> AlertContext:
        """Context for ``evaluation`` inside ``episode`` (the alert data of the approved fields)."""
        return cls(
            episode_id=episode.id if episode is not None else None,
            realert=realert,
            previous_net_usd=decimal_str(previous_net_usd)
            if previous_net_usd is not None
            else None,
            volume=_volume_payload(evaluation),
            transfer=_transfer_payload(evaluation),
            lifetime=_lifetime_payload(episode),
        )

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> AlertContext:
        """Inverse of :meth:`to_payload`; ``None`` (old tasks) means no context.

        Rows queued before version 2 carry only the episode fields: the new blocks decode to
        ``None`` (and ``v`` to 1). Unknown keys of newer versions are ignored.
        """
        if not payload:
            return cls()
        volume = payload.get("volume")
        transfer = payload.get("transfer")
        lifetime = payload.get("lifetime")
        return cls(
            episode_id=payload.get("episode_id"),
            realert=int(payload.get("realert") or 0),
            previous_net_usd=payload.get("previous_net_usd"),
            volume=_decode(AlertVolume, volume),
            transfer=_decode(AlertTransfer, transfer),
            lifetime=_decode(AlertLifetime, lifetime),
            v=int(payload.get("v") or 1),
        )


def _decode[T](kind: type[T], raw: Any) -> T | None:
    """Build ``kind`` from a dict, ignoring unknown keys; malformed blocks decode to ``None``
    (an alert without the block is better than a failed task)."""
    if not isinstance(raw, dict):
        return None
    known = set(getattr(kind, "__dataclass_fields__", {}))
    try:
        return kind(**{k: v for k, v in raw.items() if k in known})
    except TypeError:
        return None


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
        data["ip_unbound_venues"] = tuple(data.get("ip_unbound_venues", ()))
    if cls is RoutesQuarantined:
        data["routes"] = tuple(QuarantinedRoute(**r) for r in data.get("routes", ()))
    event: SystemEvent = cls(**data)
    return event


def decimal_str(value: Decimal) -> str:
    """Stable string form of a Decimal for event payloads."""
    return format(value.normalize(), "f")


__all__ = [
    "ALERT_PAYLOAD_VERSION",
    "AlertContext",
    "AlertLifetime",
    "AlertTransfer",
    "AlertVolume",
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
    "decimal_str",
    "event_from_payload",
    "event_to_payload",
]
