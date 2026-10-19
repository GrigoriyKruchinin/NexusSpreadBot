"""Opportunity episodes: one continuous run of a route meeting the profit thresholds."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from nexus.domain.spread import SpreadBreakdown, SpreadEvaluation, TransferStatus

HUNDRED = Decimal(100)


class AlertKind(StrEnum):
    """Which alert, if any, an alertable evaluation of an episode warrants."""

    FIRST = "first"
    REALERT = "realert"


class EpisodeCloseReason(StrEnum):
    """Why an episode ended."""

    GAP = "gap"
    """No qualifying evaluation for the configured gap."""
    QUARANTINED = "quarantined"
    """The route was quarantined (dead route: transfer path unverified/unavailable)."""
    RESTART = "restart"
    """The scanner restarted and the episode had already lapsed."""


@dataclass(frozen=True, slots=True)
class OpportunityEpisode:
    """A route (``symbol``, buy venue -> sell venue) continuously meeting the thresholds.

    Episodes are immutable values; transitions return updated copies.
    """

    symbol: str
    buy_exchange: str
    sell_exchange: str
    opened_at_ms: int
    last_seen_at_ms: int
    first_net_usd: Decimal
    peak_net_usd: Decimal
    last_net_usd: Decimal
    peak_net_pct: Decimal
    evaluations: int
    transfer_status: TransferStatus
    transfer_network: str | None
    id: int | None = None
    closed_at_ms: int | None = None
    close_reason: EpisodeCloseReason | None = None
    alerted_at_ms: int | None = None
    alerted_net_usd: Decimal | None = None
    """Net USD of the last alert (first alert or re-alert) - the re-alert growth baseline."""
    realerts: int = 0
    survived_latency: bool | None = None
    """Still meeting the thresholds on a REST re-check after the paper latency (``None`` =
    not checked yet / books unavailable)."""

    @classmethod
    def open(cls, evaluation: SpreadEvaluation) -> OpportunityEpisode:
        """Start an episode from a qualifying evaluation."""
        breakdown = _qualifying_breakdown(evaluation)
        return cls(
            symbol=evaluation.symbol,
            buy_exchange=evaluation.buy_exchange,
            sell_exchange=evaluation.sell_exchange,
            opened_at_ms=evaluation.evaluated_at_ms,
            last_seen_at_ms=evaluation.evaluated_at_ms,
            first_net_usd=breakdown.net_profit_usd,
            peak_net_usd=breakdown.net_profit_usd,
            last_net_usd=breakdown.net_profit_usd,
            peak_net_pct=breakdown.net_profit_pct,
            evaluations=1,
            transfer_status=evaluation.transfer.status,
            transfer_network=evaluation.transfer.network,
        )

    @property
    def route_key(self) -> str:
        """Same key format as :attr:`SpreadEvaluation.route_key`."""
        return f"{self.symbol}|{self.buy_exchange}>{self.sell_exchange}"

    @property
    def is_open(self) -> bool:
        """True until closed."""
        return self.closed_at_ms is None

    @property
    def duration_ms(self) -> int:
        """First to last qualifying evaluation."""
        return self.last_seen_at_ms - self.opened_at_ms

    def extend(self, evaluation: SpreadEvaluation) -> OpportunityEpisode:
        """Account for another qualifying evaluation of the same route."""
        if evaluation.route_key != self.route_key:
            msg = f"evaluation {evaluation.route_key} does not belong to {self.route_key}"
            raise ValueError(msg)
        if not self.is_open:
            msg = "cannot extend a closed episode"
            raise ValueError(msg)
        breakdown = _qualifying_breakdown(evaluation)
        return replace(
            self,
            last_seen_at_ms=max(self.last_seen_at_ms, evaluation.evaluated_at_ms),
            last_net_usd=breakdown.net_profit_usd,
            peak_net_usd=max(self.peak_net_usd, breakdown.net_profit_usd),
            peak_net_pct=max(self.peak_net_pct, breakdown.net_profit_pct),
            evaluations=self.evaluations + 1,
            transfer_status=evaluation.transfer.status,
            transfer_network=evaluation.transfer.network,
        )

    def close(self, at_ms: int, reason: EpisodeCloseReason) -> OpportunityEpisode:
        """Closed copy (closing an already closed episode keeps the first close)."""
        if not self.is_open:
            return self
        return replace(self, closed_at_ms=at_ms, close_reason=reason)

    @property
    def alerted(self) -> bool:
        """True once the episode produced an alert."""
        return self.alerted_at_ms is not None

    def alert_kind(self, net_usd: Decimal, realert_growth_pct: Decimal) -> AlertKind | None:
        """One alert per episode, plus a re-alert when the net profit grew by at least
        ``realert_growth_pct`` over the last alerted value."""
        if not self.is_open:
            return None
        if self.alerted_net_usd is None:
            return AlertKind.FIRST
        threshold = self.alerted_net_usd * (1 + realert_growth_pct / HUNDRED)
        return AlertKind.REALERT if net_usd >= threshold else None

    def mark_alerted(self, at_ms: int, net_usd: Decimal, kind: AlertKind) -> OpportunityEpisode:
        """Record a delivered (queued) alert."""
        return replace(
            self,
            alerted_at_ms=at_ms,
            alerted_net_usd=net_usd,
            realerts=self.realerts + (1 if kind is AlertKind.REALERT else 0),
        )

    def expired(self, now_ms: int, gap_ms: int) -> bool:
        """True when no qualifying evaluation was seen for at least ``gap_ms``."""
        return self.is_open and now_ms - self.last_seen_at_ms >= gap_ms


def _qualifying_breakdown(evaluation: SpreadEvaluation) -> SpreadBreakdown:
    if not evaluation.meets_thresholds or evaluation.breakdown is None:
        msg = f"evaluation {evaluation.route_key} does not meet the thresholds"
        raise ValueError(msg)
    return evaluation.breakdown
