"""goals + activity RPE + recommendation feedback

Adds three concerns in one migration since they're wired together in
the LLM snapshot:

1. ``goals`` — the user's training goals (race_type, target_date,
   is_primary) so the daily recommendation can periodize toward them.
2. ``activities.rpe`` + ``user_notes`` + ``rated_at`` — user's perceived
   effort + free-text notes for each workout, consumed by the snapshot's
   ``recent_rpe`` block.
3. ``recommendation_feedback`` — per-day thumbs-up/down on the previous
   day's recommendation. ``cache_key`` is audit-only (NOT a FK) because
   the insights cache has a 24h TTL and old rows are purged.

All ``op.add_column`` calls on ``activities`` are metadata-only on SQLite
(per CLAUDE.md) so the sync scheduler keeps running.

Revision ID: c1a4e8f27b10
Revises: b8f3d21e9a4c
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1a4e8f27b10"
down_revision = "b8f3d21e9a4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── goals ──────────────────────────────────────────────────────────
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("race_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_goals_is_primary", "goals", ["is_primary"])
    op.create_index("ix_goals_status", "goals", ["status"])
    op.create_index("ix_goals_target_date", "goals", ["target_date"])

    # ── activities: RPE + notes ────────────────────────────────────────
    op.add_column("activities", sa.Column("rpe", sa.Integer(), nullable=True))
    op.add_column("activities", sa.Column("user_notes", sa.Text(), nullable=True))
    op.add_column("activities", sa.Column("rated_at", sa.DateTime(), nullable=True))

    # ── recommendation_feedback ────────────────────────────────────────
    op.create_table(
        "recommendation_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "recommendation_date",
            sa.Date(),
            nullable=False,
            unique=True,
        ),
        sa.Column("cache_key", sa.String(length=32), nullable=True),
        sa.Column("vote", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recommendation_feedback_date",
        "recommendation_feedback",
        ["recommendation_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_feedback_date", table_name="recommendation_feedback"
    )
    op.drop_table("recommendation_feedback")

    op.drop_column("activities", "rated_at")
    op.drop_column("activities", "user_notes")
    op.drop_column("activities", "rpe")

    op.drop_index("ix_goals_target_date", table_name="goals")
    op.drop_index("ix_goals_status", table_name="goals")
    op.drop_index("ix_goals_is_primary", table_name="goals")
    op.drop_table("goals")
