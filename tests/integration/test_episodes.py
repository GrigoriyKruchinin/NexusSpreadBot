from dataclasses import replace
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.episodes import EpisodeCloseReason, OpportunityEpisode
from nexus.persistence.models import OpportunityEpisodeRow, SpreadEvaluationRow
from nexus.persistence.repositories import (
    EpisodeRepository,
    EvaluationRepository,
    episode_to_row,
)
from nexus.scanner.episodes import EpisodeTracker
from tests.fakes import ManualClock
from tests.support import EVALUATED_AT_MS as T0
from tests.support import make_evaluation

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]


async def test_episode_roundtrip_and_save(sessions: Sessions) -> None:
    repo = EpisodeRepository(sessions)
    episode = OpportunityEpisode.open(make_evaluation(net_usd=D("7.98101")))
    stored = await repo.open(episode)
    (loaded,) = await repo.list_open()
    assert loaded == stored == replace(episode, id=stored.id)
    updated = replace(
        loaded.extend(make_evaluation(net_usd=D("12.5"), evaluated_at_ms=T0 + 5_000)),
        alerted_at_ms=T0 + 1_000,
        alerted_net_usd=D("7.98101"),
        realerts=1,
        survived_latency=True,
    )
    await repo.save([updated])
    assert await repo.list_open() == [updated]
    assert updated.id is not None
    await repo.set_survived_latency(updated.id, False)
    assert (await repo.list_open())[0].survived_latency is False


async def test_one_open_episode_per_route(sessions: Sessions) -> None:
    repo = EpisodeRepository(sessions)
    episode = OpportunityEpisode.open(make_evaluation())
    first = await repo.open(episode)
    later = replace(episode, opened_at_ms=T0 + 5_000, last_seen_at_ms=T0 + 5_000)
    assert await repo.open(later) == first  # no second open row: the existing one is returned
    await repo.save([first.close(T0 + 60_000, EpisodeCloseReason.GAP)])
    assert (await repo.open(later)).id != first.id  # a closed episode frees the route
    with pytest.raises(IntegrityError):  # the index itself still guards raw inserts
        async with sessions.begin() as session:
            session.add(episode_to_row(episode))


async def test_closed_episode_is_never_reopened(sessions: Sessions) -> None:
    repo = EpisodeRepository(sessions)
    episode = OpportunityEpisode.open(make_evaluation())
    episode = await repo.open(episode)
    closed = episode.close(T0 + 60_000, EpisodeCloseReason.QUARANTINED)
    await repo.save([closed])
    await repo.save([replace(episode, evaluations=99)])  # stale open copy
    await repo.save([episode.close(T0 + 90_000, EpisodeCloseReason.RESTART)])
    assert await repo.list_open() == []
    async with sessions() as session:
        row = await session.get(OpportunityEpisodeRow, episode.id)
    assert row is not None
    assert (row.close_reason, row.evaluations) == ("quarantined", 1)


async def test_tracker_restart_and_evaluation_links(sessions: Sessions) -> None:
    clock = ManualClock(now=T0)
    repo = EpisodeRepository(sessions)
    tracker = EpisodeTracker(repo, close_gap_ms=60_000, clock=clock)
    evaluation = make_evaluation()
    observed = await tracker.observe([evaluation])
    (evaluation_id,) = await EvaluationRepository(sessions).add_evaluations(
        [evaluation], observed.episode_ids
    )
    async with sessions() as session:
        row = await session.get(SpreadEvaluationRow, evaluation_id)
    assert row is not None
    assert row.episode_id == observed.episode_ids[0]

    clock.now = T0 + 120_000
    restarted = EpisodeTracker(repo, close_gap_ms=60_000, clock=clock)
    closed = await restarted.start()
    assert [e.close_reason for e in closed] == [EpisodeCloseReason.RESTART]
    assert await repo.list_open() == []
    async with sessions() as session:
        linked = await session.scalar(
            select(SpreadEvaluationRow.episode_id).where(SpreadEvaluationRow.id == evaluation_id)
        )
    assert linked == observed.episode_ids[0]
