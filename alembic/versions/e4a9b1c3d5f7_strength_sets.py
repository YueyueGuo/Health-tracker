"""Manual strength training: strength_sets table

Revision ID: e4a9b1c3d5f7
Revises: d89f2a41e6c3
Create Date: 2026-04-17 10:00:00.000000

Adds the `strength_sets` table for manually-logged sets/reps/weight.
A session is an implicit grouping by `date`; no separate parent row.
`activity_id` is a nullable FK that lets the user link a session to an
existing Strava WeightTraining activity (ON DELETE SET NULL so deleting
the activity doesn't orphan the log entries).

SQLite-safe: plain `op.create_table` + explicit indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e4a9b1c3d5f7"
down_revision: Union[str, None] = "d89f2a41e6c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strength_sets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("exercise_name", sa.String(length=100), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"], ["activities.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        op.f("ix_strength_sets_activity_id"),
        "strength_sets",
        ["activity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strength_sets_date"),
        "strength_sets",
        ["date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strength_sets_exercise_name"),
        "strength_sets",
        ["exercise_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_strength_sets_exercise_name"), table_name="strength_sets")
    op.drop_index(op.f("ix_strength_sets_date"), table_name="strength_sets")
    op.drop_index(op.f("ix_strength_sets_activity_id"), table_name="strength_sets")
    op.drop_table("strength_sets")
