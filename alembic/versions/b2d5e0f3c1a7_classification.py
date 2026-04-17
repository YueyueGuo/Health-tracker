"""classification columns on activities

Revision ID: b2d5e0f3c1a7
Revises: c3e7b18f92a4
Create Date: 2026-04-16 22:08:00.000000

Uses plain ALTER TABLE ADD COLUMN (no batch mode) so it's safe to run
concurrently with a live backfill/sync. SQLite supports adding nullable
columns as a metadata-only operation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "b2d5e0f3c1a7"
down_revision: Union[str, None] = "c3e7b18f92a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("classification_type", sa.String(), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("classification_flags", sqlite.JSON(), nullable=True),
    )
    op.add_column(
        "activities",
        sa.Column("classified_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_activities_classification_type"),
        "activities",
        ["classification_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_activities_classification_type"), table_name="activities"
    )
    op.drop_column("activities", "classified_at")
    op.drop_column("activities", "classification_flags")
    op.drop_column("activities", "classification_type")
