"""Add ``shoes`` table + nullable ``shoe_id`` FK on ``activities`` and ``workouts``.

Backs the running-shoe-mileage feature (see
``docs/plans/running-shoe-mileage.md``). Schema-only change:

* New ``shoes`` table — name/brand/model, status (``active|retired``),
  shoe_type (``everyday|workout|race|long_run|trail``), user-configurable
  ``total_usable_distance_m`` lifespan, optional metadata. No DB-level
  CHECK constraints on the enums; validation lives at the Pydantic
  router layer per AGENTS.md (matches the ``goals.status`` and Apple
  Health ``source`` patterns).

* Nullable ``activities.shoe_id`` and ``workouts.shoe_id`` FKs pointing
  at ``shoes.id`` with ``ON DELETE SET NULL``. No backfill, no default
  — every existing row stays ``NULL`` until the user PATCHes it. On
  Postgres this is a metadata-only ALTER (no rewrite of the populated
  ``activities`` table); on SQLite the ``op.add_column`` path is the
  scheduler-safe one per AGENTS.md (no ``batch_alter_table``).

Cumulative shoe mileage is computed on read (``SUM`` over the two FK
columns); no stored counter, no triggers, no backfill script.

Schema notes
------------
* Timestamps are ``DateTime(timezone=True)`` — all new tables added
  after ``a9d2f6c1e3b7_pg_identity_and_tz`` declare tz-aware columns
  directly. ``updated_at`` carries ``onupdate=sa.func.now()`` at the
  SQLAlchemy layer; that's a Python-side hook (no DDL emitted) — the
  ``server_default=sa.func.now()`` is what the migration actually
  needs and matches ``e1a3b7d2c9f4_add_strength_session_links.py``.
* Autoincrement follows the post-``a9d2f6c1e3b7`` convention:
  ``sa.Integer(), primary_key=True, autoincrement=True`` (SERIAL on
  Postgres, ROWID alias on SQLite).
* The two FK columns are declared with an inline ``sa.ForeignKey(...)``
  inside ``sa.Column(...)``; SQLAlchemy / Alembic emit the constraint
  as part of the ADD COLUMN DDL, which both Postgres and SQLite accept
  for nullable columns with no default. The target ``shoes`` table is
  created earlier in the same upgrade so the constraint is valid at
  the moment it's installed.

Risk: trivial — no alters/backfills/drops; the new FK columns target
a table created in the same revision.

Revision ID: b6e9c4a7d51f
Revises: e1a3b7d2c9f4
Create Date: 2026-05-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e9c4a7d51f"
down_revision: Union[str, None] = "e1a3b7d2c9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── shoes ────────────────────────────────────────────────────────
    op.create_table(
        "shoes",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("brand", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column(
            "shoe_type",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'everyday'"),
        ),
        sa.Column(
            "status",
            sa.String(length=12),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("total_usable_distance_m", sa.Float(), nullable=True),
        sa.Column("purchased_on", sa.Date(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            nullable=False,
        ),
    )
    op.create_index("ix_shoes_status", "shoes", ["status"])
    op.create_index("ix_shoes_shoe_type", "shoes", ["shoe_type"])

    # ── activities.shoe_id ───────────────────────────────────────────
    # Nullable, no default, FK declared inline so the ADD COLUMN DDL
    # carries the constraint. Postgres treats this as a metadata-only
    # ALTER even on the populated ``activities`` table; SQLite accepts
    # the inline reference on a nullable add. Plain ``op.add_column``
    # (no ``batch_alter_table``) per AGENTS.md so the running scheduler
    # stays safe.
    op.add_column(
        "activities",
        sa.Column(
            "shoe_id",
            sa.Integer(),
            sa.ForeignKey("shoes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_activities_shoe_id", "activities", ["shoe_id"])

    # ── workouts.shoe_id ─────────────────────────────────────────────
    # Same shape on the Apple Health joined-table-inheritance row.
    op.add_column(
        "workouts",
        sa.Column(
            "shoe_id",
            sa.Integer(),
            sa.ForeignKey("shoes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_workouts_shoe_id", "workouts", ["shoe_id"])


def downgrade() -> None:
    # Mirror of upgrade in reverse order.
    op.drop_index("ix_workouts_shoe_id", table_name="workouts")
    op.drop_column("workouts", "shoe_id")

    op.drop_index("ix_activities_shoe_id", table_name="activities")
    op.drop_column("activities", "shoe_id")

    op.drop_index("ix_shoes_shoe_type", table_name="shoes")
    op.drop_index("ix_shoes_status", table_name="shoes")
    op.drop_table("shoes")
