"""
Initial schema: accounts, members, addjobs; plus indexes.

Revision ID: 0001_initial
Revises:
Create Date: 2025-08-12 00:00:00
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accounts table
    op.create_table(
        "account",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("phone", sa.String, nullable=False),
        sa.Column("session_path", sa.String, nullable=False),
        sa.Column("proxy", sa.String, nullable=True),
        sa.Column("device_string", sa.String, nullable=True),
        sa.Column("cooldown_until", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_account_cooldown_until", "account", ["cooldown_until"])

    # members table
    op.create_table(
        "member",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("username", sa.String, nullable=True),
        sa.Column("access_hash", sa.BigInteger, nullable=True),
        sa.Column("first_name", sa.String, nullable=True),
        sa.Column("last_name", sa.String, nullable=True),
        sa.Column("last_seen", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # addjobs table
    op.create_table(
        "addjob",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dest_group", sa.String, nullable=False),
        sa.Column("username", sa.String, nullable=True),
        sa.Column("member_user_id", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("account_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime, nullable=True),
    )
    # indexes for addjob
    op.create_index("ix_addjob_status_created_at", "addjob", ["status", "created_at"])
    op.create_index("ix_addjob_next_attempt_at", "addjob", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_addjob_next_attempt_at", table_name="addjob")
    op.drop_index("ix_addjob_status_created_at", table_name="addjob")
    op.drop_table("addjob")
    op.drop_index("ix_account_cooldown_until", table_name="account")
    op.drop_table("member")
    op.drop_table("account")
