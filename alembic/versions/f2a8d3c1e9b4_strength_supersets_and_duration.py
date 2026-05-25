"""Add superset + duration columns to strength_sets.

Four nullable columns to support the strength workout detail / review
page (see ``docs/plans/strength-workout-detail.md``):

* ``superset_group_id`` — integer tag, scoped to a session (date);
  exercises sharing a non-null value were performed back-to-back. Null
  means standalone. No FK / no parent table — promote to a
  ``superset_groups`` row later if we ever need round-count or rest
  metadata.
* ``order_index`` — display order across the session, so the detail
  page can render exercises in the recorded sequence instead of
  falling back to alphabetical. Null rows fall back to
  ``min(performed_at)`` per exercise.
* ``started_at`` / ``ended_at`` — session start/end stamps (tz-aware),
  written by the recorder's Start / Finish taps. Denormalized onto
  every row of the session for simplicity; the service reads them as
  ``max(ended_at) - min(started_at)`` across the date's rows.

SQLite-safe: plain ``op.add_column`` (not ``batch_alter_table``) per
AGENTS.md, all columns nullable so no ``server_default`` is needed and
the live scheduler keeps running through the migration. No backfill —
existing rows are valid as-is (no superset, alphabetical fallback
ordering, null duration).

Composite index ``ix_strength_sets_date_superset`` on
``(date, superset_group_id)`` matches the per-session grouped read
pattern used by ``session_summary``.

Chains off ``37d57cfdb27d``, the actual pre-feature single head on
this branch. ``c2f7a4e91b85`` (the strength-touching merge point) is
already in ``37d57cfdb27d``'s ancestry via
``d4f1a8b62c70 → e8f31a902b94 → f9c2e1a45b80 → a9d2f6c1e3b7``, so this
keeps the DAG single-headed and preserves the invariant the
``tests/test_alembic_env_database_url.py`` suite enforces.

Revision ID: f2a8d3c1e9b4
Revises: 37d57cfdb27d
Create Date: 2026-05-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a8d3c1e9b4"
down_revision = "37d57cfdb27d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strength_sets",
        sa.Column("superset_group_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "strength_sets",
        sa.Column("order_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "strength_sets",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strength_sets",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_strength_sets_date_superset",
        "strength_sets",
        ["date", "superset_group_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strength_sets_date_superset",
        table_name="strength_sets",
    )
    op.drop_column("strength_sets", "ended_at")
    op.drop_column("strength_sets", "started_at")
    op.drop_column("strength_sets", "order_index")
    op.drop_column("strength_sets", "superset_group_id")
