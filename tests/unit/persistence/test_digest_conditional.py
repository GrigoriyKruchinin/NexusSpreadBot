"""Episode totals with / without conditional venues (rows faked; SQL paths are integration)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

from nexus.persistence.repositories import DigestRepository

T = datetime(2026, 10, 1, tzinfo=UTC)


def _row(buy: str, sell: str, peak: str) -> Any:
    return SimpleNamespace(
        symbol="X/USDT",
        buy_exchange=buy,
        sell_exchange=sell,
        peak_net_usd=D(peak),
        peak_net_pct=D(1),
        opened_at=T,
        last_seen_at=T + timedelta(seconds=10),
        close_reason="gap",
        transfer_status="verified",
        survived_latency=None,
    )


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def scalars(self, _stmt: object) -> Any:
        return SimpleNamespace(all=lambda: self._rows)


async def test_episode_totals_all_vs_excluding_conditional() -> None:
    rows = [
        _row("binance", "okx", "5"),  # 0 conditional legs
        _row("kucoin", "okx", "4"),  # 0
        _row("bybit", "okx", "3"),  # 1 (buy)
        _row("okx", "gateio", "2"),  # 1 (sell)
        _row("bybit", "gateio", "1"),  # 2
    ]
    session: Any = _Session(rows)
    stats = await DigestRepository._episodes(session, T, T, ("bybit", "gateio"))
    assert stats.total == 5
    assert stats.total_excl_conditional == 2
    stats = await DigestRepository._episodes(session, T, T, ())
    assert stats.total_excl_conditional == stats.total == 5


async def test_empty_window_reports_zero_excl_conditional_not_unknown() -> None:
    """R2-1: a quiet day must show 'без условных 0', never 'н/д'."""
    session: Any = _Session([])
    stats = await DigestRepository._episodes(session, T, T, ("bybit", "gateio"))
    assert stats.total == 0
    assert stats.total_excl_conditional == 0
