"""add portfolio_id to paper tables (B15 shadow portfolios)

Existing rows are the single pre-B15 portfolio, backfilled as ``all``. The server default
stays ``all`` so a not-yet-updated writer keeps working during a rolling deploy. The old
single-column time/status indexes are replaced by composites led by ``portfolio_id``: every
query is per portfolio (restore, digest, per-set report), so the leading column is always bound.

Revision ID: b15a7c3e91d2
Revises: 40c869df951f
Create Date: 2026-10-23 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b15a7c3e91d2"
down_revision: str | None = "40c869df951f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("paper_trades", "paper_rebalances", "paper_balance_snapshots")


def upgrade() -> None:
    for table in TABLES:
        # Constant server default + NOT NULL: PostgreSQL backfills existing rows with 'all'
        # without rewriting the table (metadata-only since PG 11).
        op.add_column(
            table,
            sa.Column("portfolio_id", sa.String(length=32), server_default="all", nullable=False),
        )
    op.drop_index("ix_paper_trades_executed_at", table_name="paper_trades")
    op.create_index(
        "ix_paper_trades_portfolio_executed_at",
        "paper_trades",
        ["portfolio_id", "executed_at"],
        unique=False,
    )
    op.drop_index("ix_paper_rebalances_started_at", table_name="paper_rebalances")
    op.drop_index("ix_paper_rebalances_status", table_name="paper_rebalances")
    op.create_index(
        "ix_paper_rebalances_portfolio_started_at",
        "paper_rebalances",
        ["portfolio_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_paper_rebalances_portfolio_status",
        "paper_rebalances",
        ["portfolio_id", "status"],
        unique=False,
    )
    op.drop_index("ix_paper_balance_snapshots_captured_at", table_name="paper_balance_snapshots")
    op.create_index(
        "ix_paper_balance_snapshots_portfolio_captured_at",
        "paper_balance_snapshots",
        ["portfolio_id", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    # Rows of non-'all' portfolios would corrupt the single-portfolio schema (restore sums all
    # rows): they are deleted, 'all' rows are kept untouched.
    for table in TABLES:
        op.execute(sa.text(f"DELETE FROM {table} WHERE portfolio_id <> 'all'"))  # noqa: S608
    op.drop_index(
        "ix_paper_balance_snapshots_portfolio_captured_at", table_name="paper_balance_snapshots"
    )
    op.create_index(
        "ix_paper_balance_snapshots_captured_at",
        "paper_balance_snapshots",
        ["captured_at"],
        unique=False,
    )
    op.drop_index("ix_paper_rebalances_portfolio_status", table_name="paper_rebalances")
    op.drop_index("ix_paper_rebalances_portfolio_started_at", table_name="paper_rebalances")
    op.create_index("ix_paper_rebalances_status", "paper_rebalances", ["status"], unique=False)
    op.create_index(
        "ix_paper_rebalances_started_at", "paper_rebalances", ["started_at"], unique=False
    )
    op.drop_index("ix_paper_trades_portfolio_executed_at", table_name="paper_trades")
    op.create_index("ix_paper_trades_executed_at", "paper_trades", ["executed_at"], unique=False)
    for table in TABLES:
        op.drop_column(table, "portfolio_id")
