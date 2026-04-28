"""Whoop: add sleep_efficiency, sleep_consistency, sleep_need_baseline_min, sleep_debt_min

Revision ID: d4f1a8b62c70
Revises: c2f7a4e91b85
Create Date: 2026-04-27 23:18:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4f1a8b62c70"
down_revision: Union[str, None] = "c2f7a4e91b85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New nullable columns: prefer plain add_column over batch_alter_table so
    # the migration is safe to run alongside the live scheduler (per AGENTS.md).
    op.add_column(
        "sleep_sessions",
        sa.Column("sleep_efficiency", sa.Float(), nullable=True),
    )
    op.add_column(
        "sleep_sessions",
        sa.Column("sleep_consistency", sa.Float(), nullable=True),
    )
    op.add_column(
        "sleep_sessions",
        sa.Column("sleep_need_baseline_min", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sleep_sessions",
        sa.Column("sleep_debt_min", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("sleep_sessions") as batch:
        batch.drop_column("sleep_debt_min")
        batch.drop_column("sleep_need_baseline_min")
        batch.drop_column("sleep_consistency")
        batch.drop_column("sleep_efficiency")
