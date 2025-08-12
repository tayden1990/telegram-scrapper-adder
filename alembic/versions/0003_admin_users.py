"""
Add AdminUser table for multiple admins.

Revision ID: 0003_admin_users
Revises: 0002_appcontrol
Create Date: 2025-08-12 00:30:00
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_admin_users"
down_revision = "0002_appcontrol"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adminuser",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String, nullable=False, unique=True),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_adminuser_username", "adminuser", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_adminuser_username", table_name="adminuser")
    op.drop_table("adminuser")
