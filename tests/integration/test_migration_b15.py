"""B15 migration on the test DB (AC4): backfill with 'all', NOT NULL/default, indexes, the new
registry tables, row counts and a complete downgrade. CI only, never against the live DB."""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from nexus.config.groups import DatabaseSettings
from nexus.persistence.db import create_engine
from tests.db_guard import assert_test_database

pytestmark = pytest.mark.integration
PREVIOUS = "40c869df951f"
TABLES = ("paper_trades", "paper_rebalances", "paper_balance_snapshots")
NEW_TABLES = {"paper_portfolios", "paper_cap_stats"}
NEW_INDEXES = {
    "ix_paper_trades_portfolio_executed_at",
    "ix_paper_rebalances_portfolio_started_at",
    "ix_paper_rebalances_portfolio_status",
    "ix_paper_balance_snapshots_portfolio_captured_at",
    "ix_paper_portfolios_portfolio_started_at",
}
OLD_INDEXES = {
    "ix_paper_trades_executed_at",
    "ix_paper_rebalances_started_at",
    "ix_paper_rebalances_status",
    "ix_paper_balance_snapshots_captured_at",
}
TRADE = (
    "INSERT INTO paper_trades ({cols}executed_at, symbol, base, buy_exchange, sell_exchange, "
    "executed) VALUES ({vals}'{ts}', 'ABC/USDT', 'ABC', 'a', 'b', true)"
)
REBALANCE = (
    "INSERT INTO paper_rebalances ({cols}asset, from_exchange, to_exchange, amount, fee, fee_usd, "
    "network, started_at, arrives_at, status, note) VALUES ({vals}'USDT', 'a', 'b', 1, 1, 1, "
    "'TRC20', '{ts}', '{ts}', 'completed', '')"
)
SNAPSHOT = (
    "INSERT INTO paper_balance_snapshots ({cols}captured_at, exchange, asset, amount) "
    "VALUES ({vals}'{ts}', 'a', 'USDT', 1)"
)


def _run(settings: DatabaseSettings, sql: str) -> list[tuple[object, ...]]:
    async def go() -> list[tuple[object, ...]]:
        engine = create_engine(settings, pooled=False)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql))
                return [tuple(r) for r in result.fetchall()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _count(settings: DatabaseSettings, table: str) -> int:
    return int(str(_run(settings, f"SELECT count(*) FROM {table}")[0][0]))  # noqa: S608


def _indexes(settings: DatabaseSettings) -> set[str]:
    rows = _run(settings, "SELECT indexname FROM pg_indexes WHERE tablename LIKE 'paper_%'")
    return {str(r[0]) for r in rows}


def _tables(settings: DatabaseSettings) -> set[str]:
    rows = _run(
        settings, "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'paper_%'"
    )
    return {str(r[0]) for r in rows}


def _seed(settings: DatabaseSettings, ts: str, portfolio: str | None = None) -> None:
    cols, vals = ("portfolio_id, ", f"'{portfolio}', ") if portfolio else ("", "")
    for template in (TRADE, REBALANCE, SNAPSHOT):
        _run(settings, template.format(cols=cols, vals=vals, ts=ts))


def _truncate(settings: DatabaseSettings) -> None:
    _run(
        settings,
        "TRUNCATE paper_trades, paper_rebalances, paper_balance_snapshots RESTART IDENTITY CASCADE",
    )


def test_upgrade_backfills_all_and_downgrade_restores(db_settings: DatabaseSettings) -> None:
    assert_test_database(db_settings.db)
    cfg = Config("alembic.ini")
    command.downgrade(cfg, PREVIOUS)
    _truncate(db_settings)
    assert not NEW_TABLES & _tables(db_settings)
    assert _indexes(db_settings) >= OLD_INDEXES
    # pre-B15 history: two rows per table, the earliest across all tables is the rebalance
    _seed(db_settings, "2026-10-02 10:00:00+00")
    _seed(db_settings, "2026-10-03 10:00:00+00")
    _run(
        db_settings,
        "UPDATE paper_rebalances SET started_at = '2026-10-01 08:30:00+00' WHERE id = 1",
    )
    before = {t: _count(db_settings, t) for t in TABLES}
    assert before == dict.fromkeys(TABLES, 2)

    command.upgrade(cfg, "head")

    # row counts unchanged, every pre-existing row of every table is the 'all' portfolio
    assert {t: _count(db_settings, t) for t in TABLES} == before
    for table in TABLES:
        ids = _run(db_settings, f"SELECT DISTINCT portfolio_id FROM {table}")  # noqa: S608
        assert ids == [("all",)], table
        column = _run(
            db_settings,
            "SELECT is_nullable, column_default, character_maximum_length "  # noqa: S608
            "FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = 'portfolio_id'",
        )
        assert len(column) == 1, table
        nullable, default, length = column[0]
        assert nullable == "NO", table
        assert "'all'" in str(default), table
        assert length == 32, table
    # indexes: composites led by portfolio_id exist, the old single-column ones are gone
    indexes = _indexes(db_settings)
    assert indexes >= NEW_INDEXES
    assert not OLD_INDEXES & indexes
    # registry: pre-B15 history became one legacy run of 'all' at its earliest row
    assert _tables(db_settings) >= NEW_TABLES
    runs = _run(
        db_settings,
        "SELECT portfolio_id, config_hash, venues, capital_usd, "
        "started_at = '2026-10-01 08:30:00+00' FROM paper_portfolios",
    )
    assert runs == [("all", "legacy", "", 0, True)]
    assert _count(db_settings, "paper_cap_stats") == 0
    # a writer that does not know portfolio_id still lands in 'all' (rolling deploy)
    _run(
        db_settings,
        "INSERT INTO paper_balance_snapshots (captured_at, exchange, asset, amount) "
        "VALUES (now(), 'a', 'USDT', 1)",
    )
    assert _run(db_settings, "SELECT portfolio_id FROM paper_balance_snapshots WHERE id = 3") == [
        ("all",)
    ]
    _run(db_settings, "DELETE FROM paper_balance_snapshots WHERE id = 3")

    # shadow data in every touched table + the new tables
    _seed(db_settings, "2026-10-04 10:00:00+00", portfolio="excl_conditional")
    _run(
        db_settings,
        "INSERT INTO paper_portfolios (portfolio_id, started_at, venues, capital_usd, config_hash) "
        "VALUES ('excl_conditional', now(), 'a,b', 10000, 'h')",
    )
    _run(
        db_settings,
        "INSERT INTO paper_cap_stats (portfolio_id, hour) "
        "VALUES ('all', date_trunc('hour', now()))",
    )
    assert {t: _count(db_settings, t) for t in TABLES} == dict.fromkeys(TABLES, 3)

    command.downgrade(cfg, PREVIOUS)

    # only the 'all' rows survive, exactly as before; the new tables and column are gone
    assert {t: _count(db_settings, t) for t in TABLES} == before
    assert not NEW_TABLES & _tables(db_settings)
    for table in TABLES:
        assert not _run(
            db_settings,
            "SELECT 1 FROM information_schema.columns "  # noqa: S608
            f"WHERE table_name = '{table}' AND column_name = 'portfolio_id'",
        ), table
    indexes = _indexes(db_settings)
    assert indexes >= OLD_INDEXES
    assert not NEW_INDEXES & indexes

    command.upgrade(cfg, "head")
    assert _count(db_settings, "paper_portfolios") == 1  # backfilled again from the same rows


def test_upgrade_on_empty_tables_creates_no_legacy_run(db_settings: DatabaseSettings) -> None:
    assert_test_database(db_settings.db)
    cfg = Config("alembic.ini")
    command.downgrade(cfg, PREVIOUS)
    _truncate(db_settings)
    command.upgrade(cfg, "head")
    assert _count(db_settings, "paper_portfolios") == 0
