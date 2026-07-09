"""Qo'lda logist telefonlari ro'yxati (manual blocklist, admin override).

Revision ID: 20260705_logist_blocklist
Revises: 20260705_lorry_listings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260705_logist_blocklist"
down_revision = "20260705_lorry_listings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logist_blocklist",
        sa.Column("phone_norm", sa.String(length=20), primary_key=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("logist_blocklist")
