"""Add user_profile singleton table for persisted profile/preferences JSON.

Revision ID: e8f31a902b94
Revises: d4f1a8b62c70
Create Date: 2026-04-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f31a902b94"
down_revision: Union[str, None] = "d4f1a8b62c70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_profile")
