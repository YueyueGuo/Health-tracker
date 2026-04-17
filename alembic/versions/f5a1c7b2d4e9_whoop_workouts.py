"""whoop_workouts

Revision ID: f5a1c7b2d4e9
Revises: e4a9b1c3d5f7
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.sqlite import JSON

# revision identifiers, used by Alembic.
revision = "f5a1c7b2d4e9"
down_revision = "e4a9b1c3d5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whoop_workouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("whoop_id", sa.BigInteger(), unique=True, nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("end", sa.DateTime(), nullable=True),
        sa.Column("timezone_offset", sa.String(length=8), nullable=True),
        sa.Column("sport_id", sa.Integer(), nullable=True),
        sa.Column("sport_name", sa.String(length=64), nullable=True),
        sa.Column("score_state", sa.String(length=32), nullable=True),
        sa.Column("strain", sa.Float(), nullable=True),
        sa.Column("average_heart_rate", sa.Float(), nullable=True),
        sa.Column("max_heart_rate", sa.Float(), nullable=True),
        sa.Column("kilojoule", sa.Float(), nullable=True),
        sa.Column("percent_recorded", sa.Float(), nullable=True),
        sa.Column("distance_meter", sa.Float(), nullable=True),
        sa.Column("altitude_gain_meter", sa.Float(), nullable=True),
        sa.Column("altitude_change_meter", sa.Float(), nullable=True),
        sa.Column("zone_zero_ms", sa.Integer(), nullable=True),
        sa.Column("zone_one_ms", sa.Integer(), nullable=True),
        sa.Column("zone_two_ms", sa.Integer(), nullable=True),
        sa.Column("zone_three_ms", sa.Integer(), nullable=True),
        sa.Column("zone_four_ms", sa.Integer(), nullable=True),
        sa.Column("zone_five_ms", sa.Integer(), nullable=True),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("raw_data", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_whoop_workouts_whoop_id", "whoop_workouts", ["whoop_id"])
    op.create_index("ix_whoop_workouts_start", "whoop_workouts", ["start"])
    op.create_index("ix_whoop_workouts_sport_name", "whoop_workouts", ["sport_name"])
    op.create_index("ix_whoop_workouts_activity_id", "whoop_workouts", ["activity_id"])


def downgrade() -> None:
    op.drop_index("ix_whoop_workouts_activity_id", table_name="whoop_workouts")
    op.drop_index("ix_whoop_workouts_sport_name", table_name="whoop_workouts")
    op.drop_index("ix_whoop_workouts_start", table_name="whoop_workouts")
    op.drop_index("ix_whoop_workouts_whoop_id", table_name="whoop_workouts")
    op.drop_table("whoop_workouts")
