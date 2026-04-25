"""Add nullable hr_zone to activity_laps.

Per-lap heart-rate zone (1-indexed) derived from the parent activity's
``zones_data`` and the lap's ``average_heartrate``. Persisted so the
laps table can render zone tinting without recomputing on every read.
Also serves as the persistence target for the lap-zone backfill script.

Doubles as a head-merge: chains both prior heads
(``b3c6d9e8a1f4`` strength performed_at, ``c1a4e8f27b10`` goals/RPE/feedback)
back into a single linear chain.

Revision ID: c2f7a4e91b85
Revises: b3c6d9e8a1f4, c1a4e8f27b10
Create Date: 2026-04-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2f7a4e91b85"
down_revision = ("b3c6d9e8a1f4", "c1a4e8f27b10")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "activity_laps",
        sa.Column("hr_zone", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activity_laps", "hr_zone")
