"""
Add index on addjob.dest_group

Revision ID: 0004_add_index_addjob_dest_group
Revises: 0003_admin_users
Create Date: 2025-08-12 00:45:00
"""

from alembic import op
import sqlalchemy as sa

revision = '0004_add_index_addjob_dest_group'
down_revision = '0003_admin_users'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_addjob_dest_group', 'addjob', ['dest_group'])


def downgrade() -> None:
    op.drop_index('ix_addjob_dest_group', table_name='addjob')
