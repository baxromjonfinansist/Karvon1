"""User'ga notify_enabled/last_notified_at + feedbacks jadvali.

Revision ID: 20260704_notify_fb
Revises: 20260704_vehicle_type
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260704_notify_fb"
down_revision = "20260704_vehicle_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("users", sa.Column("last_notified_at", sa.DateTime(), nullable=True))
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("feedbacks")
    op.drop_column("users", "last_notified_at")
    op.drop_column("users", "notify_enabled")
