"""Load'ga vehicle_type ustunini qo'shish (isuzu/fura klassifikatsiya uchun).

Revision ID: 20260704_vehicle_type
Revises: 20260702_contact_note
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260704_vehicle_type"
down_revision = "20260702_contact_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    vehicletype = sa.Enum("isuzu", "fura", "other", name="vehicletype", create_type=False)
    op.add_column("loads", sa.Column("vehicle_type", vehicletype, nullable=True))


def downgrade() -> None:
    op.drop_column("loads", "vehicle_type")
