"""initial

Revision ID: 20260608080019
Revises:
Create Date: 2026-06-08 08:00:19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260608080019"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum turlari ---
    userrole = sa.Enum(
        "driver", "cargo_provider", "asset_owner", "staff_driver", "admin",
        name="userrole"
    )
    vehicletype = sa.Enum("isuzu", "fura", "other", name="vehicletype")
    vehicleownership = sa.Enum("independent", "leased", "company", name="vehicleownership")
    vehiclestatus = sa.Enum("available", "on_trip", "maintenance", name="vehiclestatus")
    risktier = sa.Enum("premium_safe", "standard", "budget", name="risktier")
    loadstatus = sa.Enum("pending", "open", "matched", "closed", "cancelled", name="loadstatus")
    dealstatus = sa.Enum("active", "completed", "cancelled", name="dealstatus")
    subscriptionplan = sa.Enum("basic", "premium", name="subscriptionplan")
    subscriptionstatus = sa.Enum("active", "expired", "cancelled", name="subscriptionstatus")
    transactiontype = sa.Enum("subscription", "commission", "rent", name="transactiontype")
    transactionstatus = sa.Enum("pending", "completed", "failed", name="transactionstatus")

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("role", userrole, nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("rating", sa.Numeric(3, 2), server_default="5.00"),
        sa.Column("verified", sa.Boolean(), server_default="false"),
        sa.Column(
            "sub_status",
            subscriptionstatus,
            server_default="expired",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    # --- routes ---
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("origin", sa.String(100), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("distance_km", sa.Integer(), nullable=True),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("risk_level", sa.String(50), nullable=True),
    )

    # --- driver_preferred_routes (many-to-many) ---
    op.create_table(
        "driver_preferred_routes",
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "route_id",
            sa.Integer(),
            sa.ForeignKey("routes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # --- vehicles ---
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", vehicletype, nullable=False),
        sa.Column("capacity_t", sa.Numeric(6, 2), nullable=False),
        sa.Column("ownership", vehicleownership, nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", vehiclestatus, server_default="available"),
        sa.Column("plate_number", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # --- loads ---
    op.create_table(
        "loads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_channel", sa.String(255), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id"), nullable=True),
        sa.Column("cargo_type", sa.String(100), nullable=True),
        sa.Column("weight_t", sa.Numeric(8, 2), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("risk_tier", risktier, server_default="standard"),
        sa.Column("status", loadstatus, server_default="pending"),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # --- deals ---
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("load_id", sa.Integer(), sa.ForeignKey("loads.id"), nullable=False),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agreed_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", dealstatus, server_default="active"),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # --- subscriptions ---
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan", subscriptionplan, nullable=False),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=False),
        sa.Column("status", subscriptionstatus, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", transactiontype, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", transactionstatus, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    # --- ratings ---
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "from_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("ratings")
    op.drop_table("transactions")
    op.drop_table("subscriptions")
    op.drop_table("deals")
    op.drop_table("loads")
    op.drop_table("vehicles")
    op.drop_table("driver_preferred_routes")
    op.drop_table("routes")
    op.drop_table("users")

    # Enum turlarini o'chirish
    for name in [
        "transactionstatus", "transactiontype", "subscriptionstatus",
        "subscriptionplan", "dealstatus", "loadstatus", "risktier",
        "vehiclestatus", "vehicleownership", "vehicletype", "userrole",
    ]:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
