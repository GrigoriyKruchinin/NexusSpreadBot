from dataclasses import replace
from decimal import Decimal as D

import pytest

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.domain.spread import EvaluationStatus, SpreadEvaluation
from nexus.scanner.episodes import EpisodeTracker
from tests.fakes import ManualClock, MemoryEpisodes
from tests.support import EVALUATED_AT_MS as T0
from tests.support import make_evaluation

GAP_MS = 60_000


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(now=T0)


@pytest.fixture
def repo() -> MemoryEpisodes:
    return MemoryEpisodes()


@pytest.fixture
def tracker(repo: MemoryEpisodes, clock: ManualClock) -> EpisodeTracker:
    return EpisodeTracker(repo, close_gap_ms=GAP_MS, clock=clock)


def _at(offset_ms: int, net_usd: D | None = None) -> SpreadEvaluation:
    return make_evaluation(evaluated_at_ms=T0 + offset_ms, net_usd=net_usd)


async def test_open_extend_and_link_ids(tracker: EpisodeTracker, repo: MemoryEpisodes) -> None:
    below = make_evaluation(status=EvaluationStatus.BELOW_THRESHOLD, sell_exchange="okx")
    first = await tracker.observe([make_evaluation(net_usd=D(6)), below])
    assert first.episode_ids == [1, None]
    assert [e.id for e in first.opened] == [1]
    second = await tracker.observe([_at(10_000, net_usd=D(9))])
    assert second.episode_ids == [1]
    assert second.opened == []
    stored = repo.rows[1]
    assert (stored.evaluations, stored.peak_net_usd, stored.last_seen_at_ms) == (
        2,
        D(9),
        T0 + 10_000,
    )


async def test_same_route_twice_in_one_batch(tracker: EpisodeTracker, repo: MemoryEpisodes) -> None:
    observed = await tracker.observe([make_evaluation(), _at(1, net_usd=D(20))])
    assert observed.episode_ids == [1, 1]
    assert len(observed.opened) == 1
    assert repo.rows[1].evaluations == 2
    assert repo.rows[1].peak_net_usd == D(20)


async def test_directions_are_separate_routes(tracker: EpisodeTracker) -> None:
    observed = await tracker.observe(
        [make_evaluation(), make_evaluation(buy_exchange="kucoin", sell_exchange="binance")]
    )
    assert observed.episode_ids == [1, 2]


async def test_close_after_gap_and_reopen(
    tracker: EpisodeTracker, repo: MemoryEpisodes, clock: ManualClock
) -> None:
    await tracker.observe([make_evaluation()])
    clock.now = T0 + GAP_MS - 1
    assert await tracker.close_expired() == []
    clock.now = T0 + GAP_MS
    closed = await tracker.close_expired()
    assert [(e.id, e.close_reason) for e in closed] == [(1, EpisodeCloseReason.GAP)]
    assert repo.rows[1].closed_at_ms == T0 + GAP_MS
    assert tracker.get(make_evaluation().route_key) is None
    reopened = await tracker.observe([_at(GAP_MS)])
    assert reopened.episode_ids == [2]


async def test_close_route_is_idempotent(tracker: EpisodeTracker, repo: MemoryEpisodes) -> None:
    await tracker.observe([make_evaluation()])
    key = make_evaluation().route_key
    closed = await tracker.close_route(key, EpisodeCloseReason.QUARANTINED)
    assert closed is not None
    assert closed.close_reason is EpisodeCloseReason.QUARANTINED
    assert await tracker.close_route(key, EpisodeCloseReason.QUARANTINED) is None
    assert repo.rows[1].close_reason is EpisodeCloseReason.QUARANTINED


async def test_restart_closes_lapsed_and_resumes_recent(
    repo: MemoryEpisodes, clock: ManualClock
) -> None:
    lapsed = OpportunityEpisode.open(make_evaluation(sell_exchange="okx"))
    recent = OpportunityEpisode.open(_at(GAP_MS))
    await repo.open(lapsed)
    await repo.open(recent)
    clock.now = T0 + GAP_MS + 1_000
    tracker = EpisodeTracker(repo, close_gap_ms=GAP_MS, clock=clock)
    closed = await tracker.start()
    assert [(e.id, e.close_reason) for e in closed] == [(1, EpisodeCloseReason.RESTART)]
    assert repo.rows[1].closed_at_ms == T0 + GAP_MS  # end of its gap, not restart time
    assert set(tracker.open_episodes) == {recent.route_key}
    observed = await tracker.observe([_at(GAP_MS + 1_000)])
    assert observed.episode_ids == [2]  # continues the resumed episode
    assert await EpisodeTracker(repo, close_gap_ms=GAP_MS, clock=clock).start() == []


async def test_update_ignores_closed_or_replaced_episode(
    tracker: EpisodeTracker, repo: MemoryEpisodes, clock: ManualClock
) -> None:
    opened = (await tracker.observe([make_evaluation()])).opened[0]
    await tracker.update(replace(opened, survived_latency=True))
    assert repo.rows[1].survived_latency is True
    await tracker.update(replace(opened, id=99, realerts=5))  # replaced meanwhile: ignored
    assert repo.rows[1].realerts == 0
    clock.now = T0 + GAP_MS
    await tracker.close_expired()
    await tracker.update(replace(opened, survived_latency=False))
    assert repo.rows[1].survived_latency is True  # closed row untouched


async def test_lost_insert_reply_adopts_the_stored_episode(
    tracker: EpisodeTracker, repo: MemoryEpisodes
) -> None:
    # The DB already has the route's open row (insert committed, reply lost): adopt + extend.
    await repo.open(OpportunityEpisode.open(make_evaluation(net_usd=D(6))))
    observed = await tracker.observe([_at(5_000, net_usd=D(9))])
    assert observed.episode_ids == [1]
    assert observed.opened == []
    assert (repo.rows[1].evaluations, repo.rows[1].peak_net_usd) == (2, D(9))


async def test_closed_at_is_end_of_gap_not_detection_time(
    tracker: EpisodeTracker, repo: MemoryEpisodes, clock: ManualClock
) -> None:
    await tracker.observe([make_evaluation()])
    clock.now = T0 + 10 * GAP_MS  # noticed late (e.g. a stalled loop)
    (closed,) = await tracker.close_expired()
    assert closed.closed_at_ms == T0 + GAP_MS


async def test_record_latency_only_for_the_same_open_episode(
    tracker: EpisodeTracker, repo: MemoryEpisodes
) -> None:
    opened = (await tracker.observe([make_evaluation()])).opened[0]
    assert opened.id is not None
    await tracker.record_latency(opened.route_key, opened.id + 1, survived=True)
    assert repo.rows[1].survived_latency not in (True, False)  # still unchecked
    await tracker.record_latency(opened.route_key, opened.id, survived=True)
    assert repo.rows[1].survived_latency is True
    assert tracker.open_episodes[opened.route_key].survived_latency is True


def test_gap_must_be_positive(repo: MemoryEpisodes, clock: ManualClock) -> None:
    with pytest.raises(ValueError, match="positive"):
        EpisodeTracker(repo, close_gap_ms=0, clock=clock)
