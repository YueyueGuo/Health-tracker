"""Add performed_at timestamp to strength_sets.

Nullable naive-local datetime capturing the wall-clock moment a set was
completed. Used to tie each set to a window of HR samples in the linked
Strava WeightTraining activity's cached stream. Retro entries (no
timestamp) still work — they just render without per-set HR.

Revision ID: b3c6d9e8a1f4
Revises: a7e2c5f8b1d3
Create Date: 2026-04-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c6d9e8a1f4"
down_revision: Union[str, None] = "a7e2c5f8b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN is metadata-only on SQLite — safe to run while the
    # sync scheduler is writing (see CLAUDE.md convention).
    op.add_column(
        "strength_sets",
        sa.Column("performed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strength_sets", "performed_at")
