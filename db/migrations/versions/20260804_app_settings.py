"""app_settings jadvali qo'shildi (Faza 6 — bot instruksiyasi: video/matn
saqlash uchun umumiy key-value sozlamalar jadvali, kelajakda boshqa
sozlamalar uchun ham ishlatiladi).

Revision ID: 20260804_app_settings
Revises: 20260803_user_vehicle_type
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260804_app_settings"
down_revision = "20260803_user_vehicle_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("file_id", sa.String(255), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
