"""VehicleType enum'ga 'kichik' qiymatini qo'shish (Isuzudan kichik: Porter/labo).

Revision ID: 20260705_vehicle_kichik
Revises: 20260704_pref_route
"""
from __future__ import annotations

from alembic import op

revision = "20260705_vehicle_kichik"
down_revision = "20260704_pref_route"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE transaksiya ichida ishlamaydi — autocommit blokida.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE vehicletype ADD VALUE IF NOT EXISTS 'kichik'")


def downgrade() -> None:
    # PostgreSQL enum qiymatini xavfsiz o'chira olmaydi — no-op.
    pass
