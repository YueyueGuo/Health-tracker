"""whoop_workouts.whoop_id BigInteger -> String

Whoop v2 workout ids are UUIDs (e.g. "f096bd66-9b8a-4331-9401-285008c877a8"),
not integers. The original schema (revision f5a1c7b2d4e9) used BigInteger
because v1 returned numeric ids. This migration widens the column so
upserts stop dying on `int(whoop_id)`.

The table is empty at the time of this migration (zero successful
workout syncs yet), so we can recreate it without data-loss concerns.

Revision ID: b8f3d21e9a4c
Revises: a7e2c5f8b1d3
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8f3d21e9a4c"
down_revision = "a7e2c5f8b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("whoop_workouts") as batch_op:
        batch_op.alter_column(
            "whoop_id",
            existing_type=sa.BigInteger(),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("whoop_workouts") as batch_op:
        batch_op.alter_column(
            "whoop_id",
            existing_type=sa.String(length=64),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
