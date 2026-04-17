"""Add base-elevation columns + user_locations table.

Adds elev_high_m, elev_low_m, base_elevation_m, elevation_enriched, and
location_id (FK) to the activities table. Creates user_locations for
named places (home, gym, etc.) with optional is_default flag that
auto-applies to indoor/no-GPS activities.

Revision ID: a7e2c5f8b1d3
Revises: f5a1c7b2d4e9
Create Date: 2026-04-17 22:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7e2c5f8b1d3"
down_revision: Union[str, None] = "f5a1c7b2d4e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_locations ──────────────────────────────────────────────
    op.create_table(
        "user_locations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_locations_is_default", "user_locations", ["is_default"]
    )

    # ── activities: elevation columns + location FK ────────────────
    # Plain op.add_column (metadata-only on SQLite, safe with the
    # sync scheduler running per CLAUDE.md conventions).
    op.add_column(
        "activities", sa.Column("elev_high_m", sa.Float(), nullable=True)
    )
    op.add_column(
        "activities", sa.Column("elev_low_m", sa.Float(), nullable=True)
    )
    op.add_column(
        "activities", sa.Column("base_elevation_m", sa.Float(), nullable=True)
    )
    op.add_column(
        "activities",
        sa.Column(
            "elevation_enriched",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "activities", sa.Column("location_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_activities_location_id", "activities", ["location_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_activities_location_id", table_name="activities")
    op.drop_column("activities", "location_id")
    op.drop_column("activities", "elevation_enriched")
    op.drop_column("activities", "base_elevation_m")
    op.drop_column("activities", "elev_low_m")
    op.drop_column("activities", "elev_high_m")
    op.drop_index("ix_user_locations_is_default", table_name="user_locations")
    op.drop_table("user_locations")
