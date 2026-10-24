"""Integration fixtures: a migrated PostgreSQL database (POSTGRES_* env).

Run e.g. ``POSTGRES_PORT=55432 POSTGRES_PASSWORD=... uv run pytest -m integration``.
"""

import socket
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.config.groups import DatabaseSettings
from nexus.persistence.db import create_engine, create_session_factory
from tests.db_guard import UnsafeDatabaseError, assert_test_database


def _reachable(settings: DatabaseSettings) -> bool:
    try:
        with socket.create_connection((settings.host, settings.port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def db_settings() -> DatabaseSettings:
    try:
        settings = DatabaseSettings()
    except Exception as exc:
        pytest.skip(f"database not configured: {type(exc).__name__}")
    try:
        assert_test_database(settings.db)
    except UnsafeDatabaseError as exc:
        pytest.exit(str(exc), returncode=2)  # fail loudly, before any migration/TRUNCATE
    if not _reachable(settings):
        pytest.skip("database not reachable")
    command.upgrade(Config("alembic.ini"), "head")
    return settings


@pytest.fixture
async def sessions(
    db_settings: DatabaseSettings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert_test_database(db_settings.db)  # defence in depth before TRUNCATE
    engine = create_engine(db_settings, pooled=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE alert_log, paper_trades, paper_rebalances, paper_balance_snapshots, "
                "paper_portfolios, paper_cap_stats, "
                "exchange_metadata_stats, "
                "spread_evaluations, opportunity_episodes, route_quarantine, "
                "spread_snapshots, "
                "market_pairs, "
                "exchange_health RESTART IDENTITY CASCADE"
            )
        )
    yield create_session_factory(engine)
    await engine.dispose()
