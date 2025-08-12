"""Add phone to addjob

Revision ID: 0005_add_phone_to_addjob
Revises: 0004_add_index_addjob_dest_group
Create Date: 2025-08-12
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_add_phone_to_addjob"
down_revision = "0004_add_index_addjob_dest_group"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("addjob") as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String, nullable=True))


def downgrade():
    with op.batch_alter_table("addjob") as batch_op:
        batch_op.drop_column("phone")
