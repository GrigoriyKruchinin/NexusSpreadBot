"""B15 migration on the test DB: upgrade, backfill with 'all', row counts, downgrade."""

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


def test_upgrade_backfills_all_and_downgrade_restores(db_settings: DatabaseSettings) -> None:
    assert_test_database(db_settings.db)
    cfg = Config("alembic.ini")
    command.downgrade(cfg, PREVIOUS)
    _run(
        db_settings,
        "TRUNCATE paper_trades, paper_rebalances, paper_balance_snapshots RESTART IDENTITY CASCADE",
    )
    _run(
        db_settings,
        "INSERT INTO paper_rebalances (asset, from_exchange, to_exchange, amount, fee, fee_usd, "
        "network, started_at, arrives_at, status, note) VALUES "
        "('USDT','a','b',1,1,1,'TRC20',now(),now(),'completed','')",
    )
    _run(
        db_settings,
        "INSERT INTO paper_balance_snapshots (captured_at, exchange, asset, amount) "
        "VALUES (now(),'a','USDT',1),(now(),'b','USDT',2)",
    )
    before = {t: _count(db_settings, t) for t in TABLES}
    assert before["paper_balance_snapshots"] == 2

    command.upgrade(cfg, "head")
    assert {t: _count(db_settings, t) for t in TABLES} == before
    for table in TABLES:
        ids = _run(db_settings, f"SELECT DISTINCT portfolio_id FROM {table}")  # noqa: S608
        assert ids in ([], [("all",)])

    _run(
        db_settings,
        "INSERT INTO paper_balance_snapshots (portfolio_id, captured_at, exchange, asset, amount) "
        "VALUES ('excl_conditional', now(), 'a', 'USDT', 1)",
    )
    command.downgrade(cfg, PREVIOUS)  # shadow rows are dropped, 'all' rows kept
    assert _count(db_settings, "paper_balance_snapshots") == 2
    command.upgrade(cfg, "head")
