"""
Add AppControl table for pause/resume and other flags.

Revision ID: 0002_appcontrol
Revises: 0001_initial
Create Date: 2025-08-12 00:10:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_appcontrol"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appcontrol",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("value", sa.String, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_appcontrol_key", "appcontrol", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_appcontrol_key", table_name="appcontrol")
    op.drop_table("appcontrol")
