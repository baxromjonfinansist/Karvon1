"""User'ga pref_origin/pref_destination — eng aktual yo'nalish (viloyat juftligi).

Revision ID: 20260704_pref_route
Revises: 20260704_notify_fb
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260704_pref_route"
down_revision = "20260704_notify_fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pref_origin", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("pref_destination", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pref_destination")
    op.drop_column("users", "pref_origin")
