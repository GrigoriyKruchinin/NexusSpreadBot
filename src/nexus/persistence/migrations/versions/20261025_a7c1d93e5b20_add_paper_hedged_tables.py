"""add paper_hedged_* tables (HT1 hedged transfer paper strategy)

Additive only: six new tables, no existing table is touched. ``paper_hedged_coverage`` holds the
per-UTC-hour feed coverage counters (minutes with a complete spot sweep; minutes with a fresh perp
feed per hedge venue) that the short-window verdict needs to compute active hours (spec 16.2).

Revision ID: a7c1d93e5b20
Revises: b15a7c3e91d2
Create Date: 2026-10-25 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c1d93e5b20"
down_revision: str | None = "b15a7c3e91d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "paper_hedged_coverage",
    "paper_hedged_state",
    "paper_hedged_skips",
    "paper_hedged_events",
    "paper_hedged_positions",
    "paper_hedged_runs",
)


def _run_fk() -> sa.ForeignKey:
    return sa.ForeignKey("paper_hedged_runs.id", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "paper_hedged_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("set_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venues", sa.Text(), nullable=False),
        sa.Column("capital_usd", sa.Numeric(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_hedged_runs"),
    )
    op.create_index(
        "ix_paper_hedged_runs_set_id_started_at", "paper_hedged_runs", ["set_id", "started_at"]
    )
    op.create_table(
        "paper_hedged_positions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), _run_fk(), nullable=False),
        sa.Column("position_key", sa.String(length=128), nullable=False),
        sa.Column("coin", sa.String(length=32), nullable=False),
        sa.Column("buy_venue", sa.String(length=32), nullable=False),
        sa.Column("sell_venue", sa.String(length=32), nullable=False),
        sa.Column("hedge_venue", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pnl_total", sa.Numeric(), nullable=True),
        sa.Column("hedge_break", sa.Boolean(), nullable=False),
        sa.Column("hedge_unpriced", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_hedged_positions"),
        sa.UniqueConstraint("run_id", "position_key", name="uq_paper_hedged_positions_run_key"),
    )
    op.create_index(
        "ix_paper_hedged_positions_run_id_status", "paper_hedged_positions", ["run_id", "status"]
    )
    op.create_table(
        "paper_hedged_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), _run_fk(), nullable=False),
        sa.Column("position_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("event_ms", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_hedged_events"),
        sa.UniqueConstraint(
            "run_id", "position_key", "kind", "event_ms", name="uq_paper_hedged_events_key"
        ),
    )
    op.create_table(
        "paper_hedged_skips",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), _run_fk(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coin", sa.String(length=32), nullable=False),
        sa.Column("buy_venue", sa.String(length=32), nullable=False),
        sa.Column("sell_venue", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_hedged_skips"),
    )
    op.create_index("ix_paper_hedged_skips_run_id_at", "paper_hedged_skips", ["run_id", "at"])
    op.create_table(
        "paper_hedged_state",
        sa.Column("run_id", sa.BigInteger(), _run_fk(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_paper_hedged_state"),
    )
    op.create_table(
        "paper_hedged_coverage",
        sa.Column("run_id", sa.BigInteger(), _run_fk(), nullable=False),
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "hour_start", "source", name="pk_paper_hedged_coverage"),
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
