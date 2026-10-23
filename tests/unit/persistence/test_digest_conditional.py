"""Episode totals with / without conditional venues (rows faked; SQL paths are integration)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

from sqlalchemy.dialects import postgresql

from nexus.persistence.repositories import (
    DigestRepository,
    rebalance_free_clause,
    trade_free_clause,
)

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


def _sql(clause: Any) -> str:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = clause.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    return " ".join(str(compiled).split())


def test_trade_filter_sql_excludes_either_leg() -> None:
    assert _sql(trade_free_clause(("bybit", "gateio"))) == (
        "NOT (paper_trades.buy_exchange IN ('bybit', 'gateio') "
        "OR paper_trades.sell_exchange IN ('bybit', 'gateio'))"
    )


def test_rebalance_filter_sql_excludes_from_and_to() -> None:
    assert _sql(rebalance_free_clause(("bybit",))) == (
        "NOT (paper_rebalances.from_exchange IN ('bybit') "
        "OR paper_rebalances.to_exchange IN ('bybit'))"
    )


def test_empty_conditional_list_keeps_every_row() -> None:
    # An empty IN renders as `IN (NULL) AND (1 != 1)` (always false) on each leg, so
    # NOT(false OR false) is true: excluding == all. No bare `IN ()` (a PostgreSQL syntax error).
    for clause in (trade_free_clause(()), rebalance_free_clause(())):
        sql = _sql(clause)
        assert sql.startswith("NOT (")
        assert sql.count("(1 != 1)") == 2
        assert "IN ()" not in sql
