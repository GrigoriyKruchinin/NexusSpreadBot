"""B14: digest totals for ALL venues vs EXCLUDING conditional venues (needs the test DB)."""

from collections.abc import Sequence
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.domain.digest import DigestData
from nexus.domain.episodes import OpportunityEpisode
from nexus.interfaces.repositories import PaperHolding
from nexus.persistence.repositories import DigestRepository, EpisodeRepository, PaperRepository
from nexus.simulation.portfolio import Rebalance, RebalanceStatus, Seed, TradeOutcome
from tests.support import make_breakdown, make_evaluation

pytestmark = pytest.mark.integration
Sessions = async_sessionmaker[AsyncSession]
T0 = 1_800_000_000_000
H = 3_600_000
CONDITIONAL = ("bybit", "gateio")
NET = D("7.98101")  # net profit of every trade built from make_breakdown()

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


def _trade(buy: str, sell: str, at_ms: int) -> TradeOutcome:
    return TradeOutcome("ABC/USDT", "ABC", buy, sell, at_ms, None, make_breakdown())


def _rebalance(src: str, dst: str, fee_usd: int, status: RebalanceStatus) -> Rebalance:
    return Rebalance(
        "USDT", src, dst, D(500), D(1), D(fee_usd), "TRC20", T0 + H, T0 + 2 * H, status
    )  # fmt: skip


async def _seed_paper(
    sessions: Sessions,
    routes: Sequence[tuple[str, str]],
    rebalances: Sequence[Rebalance],
    *,
    old_trade: bool = False,
) -> None:
    paper = PaperRepository(sessions)
    trades = [(_trade(buy, sell, T0 + H), None) for buy, sell in routes]
    if old_trade:  # before the window: totals are "since start", so it still counts
        trades.append((_trade("binance", "kucoin", T0 - 5 * H), None))
    await paper.commit(
        at_ms=T0 + H,
        trades=trades,
        rebalances=list(rebalances),
        holdings=[PaperHolding("binance", "USDT", D(1000), Seed(D(1000), D(1)), D(1))],
    )


async def _collect(sessions: Sessions, conditional: Sequence[str]) -> DigestData:
    repo = DigestRepository(sessions, conditional_venues=conditional)
    return await repo.collect(T0, T0 + 24 * H)


async def test_episode_totals_all_vs_excluding_conditional(sessions: Sessions) -> None:
    await _seed_episodes(sessions)
    data = await _collect(sessions, CONDITIONAL)
    assert data.conditional_venues == CONDITIONAL
    assert data.episodes.total == len(ROUTES)
    # either-leg rule: only the binance -> kucoin route touches no conditional venue
    assert data.episodes.total_excl_conditional == UNTOUCHED


async def test_paper_hedged_pnl_all_vs_excluding_conditional(sessions: Sessions) -> None:
    await _seed_paper(
        sessions,
        ROUTES,
        [
            _rebalance("binance", "kucoin", 2, RebalanceStatus.IN_FLIGHT),  # untouched
            _rebalance("kucoin", "bybit", 3, RebalanceStatus.IN_FLIGHT),  # to-leg conditional
            _rebalance("gateio", "okx", 4, RebalanceStatus.IN_FLIGHT),  # from-leg conditional
            _rebalance("okx", "kucoin", 100, RebalanceStatus.BLOCKED),  # never moved: ignored
        ],
        old_trade=True,
    )
    data = await _collect(sessions, CONDITIONAL)
    p = data.paper
    assert p is not None
    # all: 4 routes + 1 old trade; excluding: binance -> kucoin twice (window + old)
    assert p.realized_total_usd == 5 * NET
    assert p.rebalance_total_usd == D(9)
    assert p.hedged_pnl_usd == 5 * NET - 9
    assert p.realized_total_excl_conditional_usd == 2 * NET
    assert p.rebalance_total_excl_conditional_usd == D(2)
    assert p.hedged_pnl_excl_conditional_usd == 2 * NET - 2


async def test_either_leg_rule_excludes_buy_only_and_sell_only(sessions: Sessions) -> None:
    await _seed_paper(sessions, [("bybit", "kucoin"), ("binance", "gateio")], [])
    p = (await _collect(sessions, CONDITIONAL)).paper
    assert p is not None
    assert p.realized_total_usd == 2 * NET
    assert p.realized_total_excl_conditional_usd == D(0)
    assert p.hedged_pnl_excl_conditional_usd == D(0)


async def test_empty_conditional_list_excluding_equals_all(sessions: Sessions) -> None:
    await _seed_episodes(sessions)
    await _seed_paper(
        sessions, ROUTES, [_rebalance("kucoin", "bybit", 3, RebalanceStatus.IN_FLIGHT)]
    )
    data = await _collect(sessions, ())
    assert data.conditional_venues == ()
    assert data.episodes.total == data.episodes.total_excl_conditional == len(ROUTES)
    p = data.paper
    assert p is not None
    assert p.hedged_pnl_excl_conditional_usd == p.hedged_pnl_usd == len(ROUTES) * NET - 3
