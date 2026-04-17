"""Eight Sleep: add sleep_fitness_score, tnt_count, latency

Revision ID: c3e7b18f92a4
Revises: a1c4f9d2e8b0
Create Date: 2026-04-16 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3e7b18f92a4"
down_revision: Union[str, None] = "a1c4f9d2e8b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sleep_sessions") as batch:
        batch.add_column(sa.Column("sleep_fitness_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("tnt_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("latency", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sleep_sessions") as batch:
        batch.drop_column("latency")
        batch.drop_column("tnt_count")
        batch.drop_column("sleep_fitness_score")
