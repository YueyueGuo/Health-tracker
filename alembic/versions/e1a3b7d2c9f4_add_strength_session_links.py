"""Add ``strength_session_links``: link a strength session to a device workout.

Backs the "linked workout HR sets" feature (see
``docs/specs/linked-workout-hr-sets.md`` /
``docs/plans/linked-workout-hr-sets.md``). A row pairs a strength
session (keyed by ``session_date``) with exactly one device-recorded
workout — either a Strava ``activities`` row or an Apple Health
``workouts`` row (joined-table inheritance over ``health_data_points``).
The link is strictly 1:1 in both directions:

* one session_date → one link row (UNIQUE on ``session_date``);
* one device workout → at most one link row (partial UNIQUE indexes
  on ``(source, activity_id)`` and ``(source, workout_id)`` scoped to
  the relevant non-null FK).

Auto-segmentation results (per-set windows + summary status) are
cached on the row so reload of the session detail view doesn't
re-run the segmenter against the HR stream.

Schema notes
------------
* ``source`` is a 16-char string with known values ``'strava'`` and
  ``'apple_health'``. No DB-level CHECK constraint per AGENTS.md;
  enforced in application code.
* ``activity_id`` is ``sa.Integer`` (not BIGINT) to match the actual
  type of ``activities.id`` in this repo. The spec wording said
  BIGINT but the existing column is Integer; the migration uses
  Integer to keep the FK type-compatible.
* ``workout_id`` FKs ``workouts.id`` which is itself a joined-table
  inheritance PK / FK back to ``health_data_points.id``. Integer
  matches the parent column.
* ``segmentation_payload`` uses ``sa.JSON()`` — same shape used by
  ``health_data_points.raw_payload`` (see ``37d57cfdb27d``). Works on
  both SQLite and Postgres.
* All timestamps are ``DateTime(timezone=True)`` per the
  ``a9d2f6c1e3b7_pg_identity_and_tz`` precedent. New tables created
  *after* that migration just declare tz-aware columns directly; no
  separate ALTER TABLE step is needed.
* Autoincrement follows the convention used in ``37d57cfdb27d`` and
  other post-``a9d2f6c1e3b7`` migrations: ``sa.Integer(),
  primary_key=True, autoincrement=True``. SQLAlchemy emits SERIAL on
  Postgres which auto-increments; this matches how every other
  post-IDENTITY-fix table was added.

Partial UNIQUE indexes
----------------------
Postgres supports partial indexes via ``WHERE``; SQLite has supported
them since 3.8 and this repo's local dev runs on 3.45. SQLAlchemy
takes the predicate via ``sqlite_where`` / ``postgresql_where``
kwargs on ``op.create_index``. Both dialects are wired explicitly so
the migration works against either backend.

Backfill
--------
Existing ``strength_sets`` rows may carry a non-null ``activity_id``
from the pre-feature flow (the legacy POST ``/strength/sets`` path
accepts an ``activity_id``; see backend task 8 in the plan). One row
per distinct ``(date, activity_id)`` is inserted with
``source='strava'`` and ``segmentation_status='pending'`` so the
first GET against the session triggers segmentation. If no
``strength_sets`` row has a non-null ``activity_id``, the backfill
is a no-op.

Revision ID: e1a3b7d2c9f4
Revises: 37d57cfdb27d
Create Date: 2026-05-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a3b7d2c9f4"
down_revision: Union[str, None] = "37d57cfdb27d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Dialect-aware backfill SQL. SQLite uses CURRENT_TIMESTAMP (UTC ISO
# string); Postgres uses NOW() which yields a tz-aware timestamptz.
# Both write into a DateTime(timezone=True) column.
_BACKFILL_SQLITE = """
INSERT INTO strength_session_links (
    session_date, source, activity_id, segmentation_status,
    linked_at, updated_at
)
SELECT
    date,
    'strava',
    activity_id,
    'pending',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM strength_sets
WHERE activity_id IS NOT NULL
GROUP BY date, activity_id
"""

_BACKFILL_POSTGRES = """
INSERT INTO strength_session_links (
    session_date, source, activity_id, segmentation_status,
    linked_at, updated_at
)
SELECT
    date,
    'strava',
    activity_id,
    'pending',
    NOW(),
    NOW()
FROM strength_sets
WHERE activity_id IS NOT NULL
GROUP BY date, activity_id
"""


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    op.create_table(
        "strength_session_links",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        # Integer (not BigInteger) to match activities.id / workouts.id
        # types in this repo. See module docstring.
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.Column("workout_id", sa.Integer(), nullable=True),
        sa.Column(
            "segmentation_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("segmentation_detected_count", sa.Integer(), nullable=True),
        sa.Column("segmentation_target_count", sa.Integer(), nullable=True),
        sa.Column("segmentation_payload", sa.JSON(), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
            ondelete="SET NULL",
        ),
    )

    # UNIQUE on session_date — one manual session links to one device
    # workout. Created as an explicit index (not via column
    # ``unique=True``) so the downgrade has a named index to drop.
    op.create_index(
        "ix_strength_session_links_session_date",
        "strength_session_links",
        ["session_date"],
        unique=True,
    )

    # Plain index on source for the (source, ref_id) lookup hot path
    # used by the link service. Cheap on a tiny table; useful when the
    # router checks "is this device workout already linked?".
    op.create_index(
        "ix_strength_session_links_source",
        "strength_session_links",
        ["source"],
    )

    # Partial UNIQUE: one device workout (Strava) → at most one link.
    # SQLite 3.8+ supports partial indexes; this repo's local dev runs
    # 3.45. Postgres has supported them since 7.x. Both dialect kwargs
    # are passed so the migration produces the same constraint on
    # either backend.
    op.create_index(
        "ix_strength_session_links_source_activity",
        "strength_session_links",
        ["source", "activity_id"],
        unique=True,
        sqlite_where=sa.text("activity_id IS NOT NULL"),
        postgresql_where=sa.text("activity_id IS NOT NULL"),
    )

    # Same pattern for the Apple Health side.
    op.create_index(
        "ix_strength_session_links_source_workout",
        "strength_session_links",
        ["source", "workout_id"],
        unique=True,
        sqlite_where=sa.text("workout_id IS NOT NULL"),
        postgresql_where=sa.text("workout_id IS NOT NULL"),
    )

    # Backfill from existing strength_sets.activity_id. Dialect-branched
    # so the timestamp expression is native to the backend (NOW() on
    # Postgres, CURRENT_TIMESTAMP on SQLite). No-op when no rows match.
    if dialect_name == "postgresql":
        op.execute(sa.text(_BACKFILL_POSTGRES))
    else:
        # SQLite (local dev) and any other dialect — CURRENT_TIMESTAMP
        # is ANSI-SQL and supported everywhere we care about.
        op.execute(sa.text(_BACKFILL_SQLITE))


def downgrade() -> None:
    # Drop indexes in reverse-creation order, then the table itself.
    op.drop_index(
        "ix_strength_session_links_source_workout",
        table_name="strength_session_links",
    )
    op.drop_index(
        "ix_strength_session_links_source_activity",
        table_name="strength_session_links",
    )
    op.drop_index(
        "ix_strength_session_links_source",
        table_name="strength_session_links",
    )
    op.drop_index(
        "ix_strength_session_links_session_date",
        table_name="strength_session_links",
    )
    op.drop_table("strength_session_links")
