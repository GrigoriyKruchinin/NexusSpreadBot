"""episode message id and alert budget for edit-in-place alerts (S1-tool T5)

Revision ID: b7d2c4e6a1f3
Revises: 8e1f4a7c2b90
Create Date: 2026-10-25 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d2c4e6a1f3"
down_revision: str | None = "8e1f4a7c2b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "opportunity_episodes", sa.Column("alert_message_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "opportunity_episodes", sa.Column("alert_evaluation_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "opportunity_episodes",
        sa.Column("alert_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "alert_hour_budget",
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("suppressed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary_message_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("window_start", name=op.f("pk_alert_hour_budget")),
    )


def downgrade() -> None:
    op.drop_table("alert_hour_budget")
    op.drop_column("opportunity_episodes", "alert_context")
    op.drop_column("opportunity_episodes", "alert_evaluation_id")
    op.drop_column("opportunity_episodes", "alert_message_id")
