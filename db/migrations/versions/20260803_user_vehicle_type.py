"""User'ga vehicle_type va capacity_t ustunlarini qo'shish (Faza 3.3 — DriverReg
oqimida yig'ilgan mashina ma'lumoti endi bazaga saqlanadi, avval tashlab
yuborilardi).

Revision ID: 20260803_user_vehicle_type
Revises: 20260710_user_activity
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_user_vehicle_type"
down_revision = "20260710_user_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "vehicletype" enum turi bazada allaqachon bor (vehicles.type,
    # loads.vehicle_type uchun yaratilgan) — shu tur qayta ishlatiladi.
    vehicletype = sa.Enum(
        "kichik", "isuzu", "fura", "other", name="vehicletype", create_type=False
    )
    op.add_column("users", sa.Column("vehicle_type", vehicletype, nullable=True))
    op.add_column("users", sa.Column("capacity_t", sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "capacity_t")
    op.drop_column("users", "vehicle_type")
