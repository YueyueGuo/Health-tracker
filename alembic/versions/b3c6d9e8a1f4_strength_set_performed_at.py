"""Add nullable performed_at to strength_sets.

Naive-local wall-clock timestamp captured in Live entry mode (tap
"Log set" between reps). Optional — Retro entries leave it NULL and
still render normally. Enables per-set HR slicing against cached
Strava streams in a follow-up slice.

Revision ID: b3c6d9e8a1f4
Revises: a7e2c5f8b1d3
Create Date: 2026-04-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b3c6d9e8a1f4"
down_revision = "a7e2c5f8b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strength_sets",
        sa.Column("performed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strength_sets", "performed_at")
