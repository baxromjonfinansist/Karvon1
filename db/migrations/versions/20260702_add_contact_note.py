"""Load'ga contact_phone va note ustunlarini qo'shish.

Revision ID: 20260702_contact_note
Revises: 20260608080019
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_contact_note"
down_revision = "20260608080019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("loads", sa.Column("contact_phone", sa.String(length=30), nullable=True))
    op.add_column("loads", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("loads", "note")
    op.drop_column("loads", "contact_phone")
