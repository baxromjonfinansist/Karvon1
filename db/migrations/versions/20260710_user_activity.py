"""User'ga aktivlik kuzatuvi: last_active_at + last_feed_view_at (dashboard uchun).

Revision ID: 20260710_user_activity
Revises: 20260705_logist_blocklist
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260710_user_activity"
down_revision = "20260705_logist_blocklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_active_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("last_feed_view_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_last_active_at", "users", ["last_active_at"])


def downgrade() -> None:
    op.drop_index("ix_users_last_active_at", table_name="users")
    op.drop_column("users", "last_feed_view_at")
    op.drop_column("users", "last_active_at")
