"""loads.first_time_phone ustuni qo'shildi (1-qo'l ishonch yorlig'i uchun).

Revision ID: 20260805_load_first_time_phone
Revises: 20260804_app_settings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260805_load_first_time_phone"
down_revision = "20260804_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "loads",
        sa.Column(
            "first_time_phone", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("loads", "first_time_phone")
