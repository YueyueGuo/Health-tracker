"""Apple Health workouts: polymorphic health_data_points + workouts + workout_laps.

Introduces the polymorphic health-data ingestion scaffold described in
`docs/plans/apple-health-workouts.md` and `docs/decisions/0002-apple-
health-polymorphic-workouts.md`.

Creates three new tables:

* ``health_data_points`` — polymorphic base for any HealthKit-style
  sample (workout, steps, sleep, …). Carries source/data_type/external_id
  natural key plus a self-referential ``superseded_by_id`` for dedup.
* ``workouts`` — joined-table-inheritance subtype keyed by the same
  ``id`` as its parent ``health_data_points`` row.
* ``workout_laps`` — mirrors the shape of ``activity_laps`` for the
  metrics we can extract from HealthKit lap events.

Also adds three nullable back-compat columns to ``activities``:

* ``source``      — defaults backfilled to ``'strava'``.
* ``external_id`` — defaults backfilled to ``CAST(strava_id AS TEXT)``.
* ``superseded_by_id`` — indexed, **no FK**; points into
  ``health_data_points.id`` cross-table by design (see ADR 0002).

All schema changes use plain ``op.add_column`` / ``op.create_table``
(no ``batch_alter_table``) so they're safe to run alongside the live
scheduler on SQLite. ``sa.JSON()`` is used for ``raw_payload`` to keep
SQLite-in-tests compatible. No CHECK constraints on the ``source`` enum;
that's enforced in app code per AGENTS.md.

Revision ID: 37d57cfdb27d
Revises: a9d2f6c1e3b7
Create Date: 2026-05-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37d57cfdb27d"
down_revision: Union[str, None] = "a9d2f6c1e3b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── health_data_points: polymorphic base ─────────────────────────
    op.create_table(
        "health_data_points",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
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
            ["superseded_by_id"],
            ["health_data_points.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "source",
            "data_type",
            "external_id",
            name="uq_health_data_points_source_type_ext",
        ),
    )
    op.create_index(
        "ix_health_data_points_source",
        "health_data_points",
        ["source"],
    )
    op.create_index(
        "ix_health_data_points_data_type",
        "health_data_points",
        ["data_type"],
    )
    op.create_index(
        "ix_health_data_points_start_time",
        "health_data_points",
        ["start_time"],
    )
    op.create_index(
        "ix_health_data_points_superseded_by_id",
        "health_data_points",
        ["superseded_by_id"],
    )
    # Composite index to make dedup window scans on
    # (data_type, start_time) cheap. Plain B-tree, Postgres + SQLite OK.
    op.create_index(
        "ix_health_data_points_data_type_start_time",
        "health_data_points",
        ["data_type", "start_time"],
    )

    # ── workouts: joined-table-inheritance subtype ────────────────────
    # ``id`` is both PK and FK to health_data_points.id (single column
    # serves both roles, classic joined-table inheritance).
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False, nullable=False),
        sa.Column("activity_type", sa.String(length=48), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("active_energy_kcal", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("avg_speed_mps", sa.Float(), nullable=True),
        sa.Column("avg_pace_s_per_km", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Float(), nullable=True),
        sa.Column("total_elevation_m", sa.Float(), nullable=True),
        sa.Column("activity_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["id"],
            ["health_data_points.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_workouts_activity_type", "workouts", ["activity_type"])
    op.create_index("ix_workouts_activity_id", "workouts", ["activity_id"])

    # ── workout_laps: mirrors activity_laps shape ────────────────────
    op.create_table(
        "workout_laps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column("lap_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("elapsed_time_s", sa.Integer(), nullable=True),
        sa.Column("moving_time_s", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("avg_speed_mps", sa.Float(), nullable=True),
        sa.Column("max_speed_mps", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Float(), nullable=True),
        sa.Column("avg_cadence", sa.Float(), nullable=True),
        sa.Column("total_elevation_m", sa.Float(), nullable=True),
        sa.Column("split", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workout_id",
            "lap_index",
            name="uq_workout_laps_workout_lap_index",
        ),
    )
    op.create_index("ix_workout_laps_workout_id", "workout_laps", ["workout_id"])

    # ── activities: additive back-compat columns ─────────────────────
    # Plain op.add_column (NOT batch_alter_table) per AGENTS.md —
    # SQLite-safe alongside the live scheduler.
    op.add_column(
        "activities",
        sa.Column("source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("external_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_activities_superseded_by_id",
        "activities",
        ["superseded_by_id"],
    )

    # ── Backfill ─────────────────────────────────────────────────────
    # Both UPDATEs are idempotent and portable across SQLite + Postgres.
    # `CAST(... AS TEXT)` is ANSI-SQL; both dialects accept it.
    op.execute("UPDATE activities SET source = 'strava' WHERE source IS NULL")
    op.execute(
        "UPDATE activities SET external_id = CAST(strava_id AS TEXT) "
        "WHERE external_id IS NULL"
    )


def downgrade() -> None:
    # Reverse-order teardown. Plain drop_column on activities — accept
    # the SQLite limitation, consistent with other downgrades in this
    # repo (see a7e2c5f8b1d3_elevation_and_user_locations.py).
    op.drop_index("ix_activities_superseded_by_id", table_name="activities")
    op.drop_column("activities", "superseded_by_id")
    op.drop_column("activities", "external_id")
    op.drop_column("activities", "source")

    op.drop_index("ix_workout_laps_workout_id", table_name="workout_laps")
    op.drop_table("workout_laps")

    op.drop_index("ix_workouts_activity_id", table_name="workouts")
    op.drop_index("ix_workouts_activity_type", table_name="workouts")
    op.drop_table("workouts")

    op.drop_index(
        "ix_health_data_points_data_type_start_time",
        table_name="health_data_points",
    )
    op.drop_index(
        "ix_health_data_points_superseded_by_id",
        table_name="health_data_points",
    )
    op.drop_index(
        "ix_health_data_points_start_time",
        table_name="health_data_points",
    )
    op.drop_index(
        "ix_health_data_points_data_type",
        table_name="health_data_points",
    )
    op.drop_index(
        "ix_health_data_points_source",
        table_name="health_data_points",
    )
    op.drop_table("health_data_points")
