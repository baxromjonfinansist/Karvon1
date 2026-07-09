"""LORRY logist aniqlash uchun tarix jadvali (route diversity, 12h window).

Revision ID: 20260705_lorry_listings
Revises: 20260705_vehicle_kichik
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260705_lorry_listings"
down_revision = "20260705_vehicle_kichik"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lorry_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone_norm", sa.String(length=20), nullable=False),
        sa.Column("origin_canon", sa.String(length=100), nullable=True),
        sa.Column("dest_canon", sa.String(length=100), nullable=True),
        sa.Column("source_group", sa.String(length=255), nullable=True),
        sa.Column("classification", sa.String(length=20), server_default="cargo", nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lorry_listings_phone_norm", "lorry_listings", ["phone_norm"])
    op.create_index("ix_lorry_listings_posted_at", "lorry_listings", ["posted_at"])
    op.create_index("ix_lorry_phone_posted", "lorry_listings", ["phone_norm", "posted_at"])


def downgrade() -> None:
    op.drop_index("ix_lorry_phone_posted", table_name="lorry_listings")
    op.drop_index("ix_lorry_listings_posted_at", table_name="lorry_listings")
    op.drop_index("ix_lorry_listings_phone_norm", table_name="lorry_listings")
    op.drop_table("lorry_listings")
