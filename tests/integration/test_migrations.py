"""The squashed migration history (T2): one head, no drift against the ORM, no paper tables."""

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from nexus.config.groups import DatabaseSettings
from nexus.persistence.db import create_engine

pytestmark = pytest.mark.integration


HEAD = "b7d2c4e6a1f3"


def test_linear_history_on_top_of_the_squashed_initial_schema() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    revisions = [r.revision for r in script.walk_revisions()]
    assert revisions == [HEAD, "8e1f4a7c2b90"]  # newest first
    assert script.get_heads() == [HEAD]


def test_alembic_check_has_no_drift(db_settings: DatabaseSettings) -> None:
    command.check(Config("alembic.ini"))  # raises CommandError on autogenerate diff


async def test_no_paper_tables_and_head_stamped(db_settings: DatabaseSettings) -> None:
    engine = create_engine(db_settings, pooled=False)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    finally:
        await engine.dispose()
    assert not [t for t in tables if t.startswith("paper_")]
    assert version == HEAD
