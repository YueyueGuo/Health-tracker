"""laps, zones, enrichment tracking; drop has_streams

Revision ID: a1c4f9d2e8b0
Revises: 353259d46b97
Create Date: 2026-04-16 21:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = "a1c4f9d2e8b0"
down_revision: Union[str, None] = "353259d46b97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── activities: add new columns ────────────────────────────────────────
    with op.batch_alter_table("activities") as batch:
        batch.add_column(sa.Column("kilojoules", sa.Float(), nullable=True))
        batch.add_column(sa.Column("device_watts", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("workout_type", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("available_zones", sqlite.JSON(), nullable=True))
        batch.add_column(sa.Column("zones_data", sqlite.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "enrichment_status",
                sa.String(),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(sa.Column("enrichment_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("enriched_at", sa.DateTime(), nullable=True))
        batch.drop_column("has_streams")

    op.create_index(
        op.f("ix_activities_enrichment_status"),
        "activities",
        ["enrichment_status"],
        unique=False,
    )

    # Mark all existing rows for re-enrichment so they pick up laps/zones/etc.
    op.execute(
        "UPDATE activities SET enrichment_status = 'pending', enriched_at = NULL"
    )

    # ── activity_laps: new table ───────────────────────────────────────────
    op.create_table(
        "activity_laps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("lap_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("elapsed_time", sa.Integer(), nullable=True),
        sa.Column("moving_time", sa.Integer(), nullable=True),
        sa.Column("distance", sa.Float(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("average_speed", sa.Float(), nullable=True),
        sa.Column("max_speed", sa.Float(), nullable=True),
        sa.Column("average_heartrate", sa.Float(), nullable=True),
        sa.Column("max_heartrate", sa.Float(), nullable=True),
        sa.Column("average_cadence", sa.Float(), nullable=True),
        sa.Column("average_watts", sa.Float(), nullable=True),
        sa.Column("total_elevation_gain", sa.Float(), nullable=True),
        sa.Column("pace_zone", sa.Integer(), nullable=True),
        sa.Column("split", sa.Integer(), nullable=True),
        sa.Column("start_index", sa.Integer(), nullable=True),
        sa.Column("end_index", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["activity_id"], ["activities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "lap_index"),
    )
    op.create_index(
        op.f("ix_activity_laps_activity_id"),
        "activity_laps",
        ["activity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_activity_laps_activity_id"), table_name="activity_laps")
    op.drop_table("activity_laps")

    op.drop_index(op.f("ix_activities_enrichment_status"), table_name="activities")

    with op.batch_alter_table("activities") as batch:
        batch.add_column(
            sa.Column("has_streams", sa.Boolean(), nullable=False, server_default="0")
        )
        batch.drop_column("enriched_at")
        batch.drop_column("enrichment_error")
        batch.drop_column("enrichment_status")
        batch.drop_column("zones_data")
        batch.drop_column("available_zones")
        batch.drop_column("workout_type")
        batch.drop_column("device_watts")
        batch.drop_column("kilojoules")
