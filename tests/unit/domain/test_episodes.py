from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.episodes import AlertKind, EpisodeCloseReason, OpportunityEpisode
from nexus.domain.spread import EvaluationStatus, TransferQuote, TransferStatus
from tests.support import EVALUATED_AT_MS as T0
from tests.support import make_evaluation


def test_open_from_qualifying_evaluation() -> None:
    episode = OpportunityEpisode.open(make_evaluation(net_usd=D(8)))
    assert (episode.opened_at_ms, episode.last_seen_at_ms) == (T0, T0)
    assert episode.first_net_usd == episode.peak_net_usd == episode.last_net_usd == D(8)
    assert episode.peak_net_pct == D("0.8")
    assert episode.evaluations == 1
    assert episode.transfer_status is TransferStatus.VERIFIED
    assert episode.transfer_network == "TRC20"
    assert episode.is_open
    assert episode.route_key == make_evaluation().route_key


@pytest.mark.parametrize(
    "evaluation",
    [
        make_evaluation(status=EvaluationStatus.BELOW_THRESHOLD),
        make_evaluation(status=EvaluationStatus.TRANSFER_UNAVAILABLE),
        make_evaluation(with_breakdown=False),
    ],
)
def test_non_qualifying_evaluation_cannot_open(evaluation: object) -> None:
    with pytest.raises(ValueError, match="thresholds"):
        OpportunityEpisode.open(evaluation)  # type: ignore[arg-type]


def test_unverified_profitable_evaluation_opens_episode() -> None:
    unverified = make_evaluation(
        status=EvaluationStatus.TRANSFER_UNVERIFIED,
        transfer=TransferQuote(TransferStatus.UNKNOWN),
    )
    assert OpportunityEpisode.open(unverified).transfer_status is TransferStatus.UNKNOWN


def test_extend_tracks_peak_last_and_count() -> None:
    episode = OpportunityEpisode.open(make_evaluation(net_usd=D(6)))
    episode = episode.extend(make_evaluation(net_usd=D(12), evaluated_at_ms=T0 + 10_000))
    episode = episode.extend(
        make_evaluation(
            net_usd=D(7),
            evaluated_at_ms=T0 + 20_000,
            status=EvaluationStatus.TRANSFER_UNVERIFIED,
            transfer=TransferQuote(TransferStatus.UNKNOWN),
        )
    )
    assert (episode.first_net_usd, episode.peak_net_usd, episode.last_net_usd) == (
        D(6),
        D(12),
        D(7),
    )
    assert episode.peak_net_pct == D("1.2")
    assert episode.evaluations == 3
    assert episode.duration_ms == 20_000
    assert episode.transfer_status is TransferStatus.UNKNOWN  # latest status wins


def test_extend_rejects_other_route_and_closed_episode() -> None:
    episode = OpportunityEpisode.open(make_evaluation())
    with pytest.raises(ValueError, match="does not belong"):
        episode.extend(make_evaluation(sell_exchange="okx"))
    closed = episode.close(T0 + 1, EpisodeCloseReason.GAP)
    with pytest.raises(ValueError, match="closed"):
        closed.extend(make_evaluation())


def test_close_is_idempotent() -> None:
    episode = OpportunityEpisode.open(make_evaluation())
    closed = episode.close(T0 + 60_000, EpisodeCloseReason.GAP)
    assert (closed.closed_at_ms, closed.close_reason) == (T0 + 60_000, EpisodeCloseReason.GAP)
    assert closed.close(T0 + 90_000, EpisodeCloseReason.RESTART) == closed


@pytest.mark.parametrize(("elapsed", "expired"), [(59_999, False), (60_000, True)])
def test_gap_boundary(elapsed: int, expired: bool) -> None:
    episode = OpportunityEpisode.open(make_evaluation())
    assert episode.expired(T0 + elapsed, 60_000) is expired
    assert not replace(episode, closed_at_ms=T0).expired(T0 + elapsed, 60_000)


def test_alert_kind_first_then_growth_based_realerts() -> None:
    episode = OpportunityEpisode.open(make_evaluation(net_usd=D(8)))
    assert episode.alert_kind(D(8), D(50)) is AlertKind.FIRST
    alerted = episode.mark_alerted(T0 + 1, D(8), AlertKind.FIRST)
    assert (alerted.alerted_at_ms, alerted.alerted_net_usd, alerted.realerts) == (
        T0 + 1,
        D(8),
        0,
    )
    assert alerted.alert_kind(D("11.99"), D(50)) is None
    assert alerted.alert_kind(D(12), D(50)) is AlertKind.REALERT  # exactly +50 %
    realerted = alerted.mark_alerted(T0 + 2, D(12), AlertKind.REALERT)
    assert (realerted.alerted_net_usd, realerted.realerts) == (D(12), 1)
    assert realerted.alert_kind(D("17.99"), D(50)) is None  # baseline moved to $12
    assert realerted.alert_kind(D(18), D(50)) is AlertKind.REALERT
    assert realerted.close(T0 + 3, EpisodeCloseReason.GAP).alert_kind(D(99), D(50)) is None


def test_unverified_since_tracks_the_current_unverified_run() -> None:
    unknown = TransferQuote(TransferStatus.UNKNOWN)
    episode = OpportunityEpisode.open(make_evaluation())
    assert episode.unverified_since_ms is None
    episode = episode.extend(
        make_evaluation(
            status=EvaluationStatus.TRANSFER_UNVERIFIED, transfer=unknown, evaluated_at_ms=T0 + 5
        )
    )
    assert episode.unverified_since_ms == T0 + 5
    episode = episode.extend(
        make_evaluation(
            status=EvaluationStatus.TRANSFER_UNVERIFIED, transfer=unknown, evaluated_at_ms=T0 + 9
        )
    )
    assert episode.unverified_since_ms == T0 + 5  # run continues
    episode = episode.extend(make_evaluation(evaluated_at_ms=T0 + 12))
    assert episode.unverified_since_ms is None  # verified again: run reset
    opened_unverified = OpportunityEpisode.open(
        make_evaluation(status=EvaluationStatus.TRANSFER_UNVERIFIED, transfer=unknown)
    )
    assert opened_unverified.unverified_since_ms == T0
