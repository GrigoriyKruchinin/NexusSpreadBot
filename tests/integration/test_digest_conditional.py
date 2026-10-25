"""B14: episode totals for ALL venues vs EXCLUDING conditional venues (needs the test DB)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.digest import DigestData
from nexus.domain.episodes import OpportunityEpisode
from nexus.persistence.repositories import DigestRepository, EpisodeRepository
from tests.support import make_evaluation

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
H = 3_600_000
CONDITIONAL = ("bybit", "gateio")

# (buy, sell): touches 0, 1 (buy leg), 1 (sell leg) and 2 conditional venues.
ROUTES = [
    ("binance", "kucoin"),
    ("bybit", "kucoin"),
    ("binance", "gateio"),
    ("gateio", "bybit"),
]
UNTOUCHED = 1


async def _seed_episodes(sessions: Sessions) -> None:
    repo = EpisodeRepository(sessions)
    for i, (buy, sell) in enumerate(ROUTES):
        evaluation = make_evaluation(
            symbol=f"T{i}/USDT", buy_exchange=buy, sell_exchange=sell, evaluated_at_ms=T0 + H
        )
        await repo.open(OpportunityEpisode.open(evaluation))


async def _collect(sessions: Sessions, conditional: tuple[str, ...]) -> DigestData:
    repo = DigestRepository(sessions, conditional_venues=conditional)
    return await repo.collect(T0, T0 + 24 * H)


async def test_episode_totals_all_vs_excluding_conditional(sessions: Sessions) -> None:
    await _seed_episodes(sessions)
    data = await _collect(sessions, CONDITIONAL)
    assert data.conditional_venues == CONDITIONAL
    assert data.episodes.total == len(ROUTES)
    # either-leg rule: only the binance -> kucoin route touches no conditional venue
    assert data.episodes.total_excl_conditional == UNTOUCHED


async def test_empty_conditional_list_excluding_equals_all(sessions: Sessions) -> None:
    await _seed_episodes(sessions)
    data = await _collect(sessions, ())
    assert data.conditional_venues == ()
    assert data.episodes.total == data.episodes.total_excl_conditional == len(ROUTES)
