"""Eight Sleep: wake-count, WASO, out-of-bed, and per-event wake_events JSON

Revision ID: d89f2a41e6c3
Revises: b2d5e0f3c1a7
Create Date: 2026-04-16 18:25:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = "d89f2a41e6c3"
down_revision: Union[str, None] = "b2d5e0f3c1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sleep_sessions") as batch:
        batch.add_column(sa.Column("wake_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("waso_duration", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("out_of_bed_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("out_of_bed_duration", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("wake_events", sqlite.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sleep_sessions") as batch:
        batch.drop_column("wake_events")
        batch.drop_column("out_of_bed_duration")
        batch.drop_column("out_of_bed_count")
        batch.drop_column("waso_duration")
        batch.drop_column("wake_count")
