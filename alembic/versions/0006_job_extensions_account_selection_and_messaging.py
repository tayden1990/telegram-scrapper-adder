"""Job extensions: kind, allowed accounts, batch id, message text

Revision ID: 0006_job_extensions_account_selection_and_messaging
Revises: 0005_add_phone_to_addjob
Create Date: 2025-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = '0006_job_extensions_account_selection_and_messaging'
down_revision = '0005_add_phone_to_addjob'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('addjob') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String, nullable=False, server_default='add'))
        batch_op.add_column(sa.Column('allowed_account_ids', sa.String, nullable=True))
        batch_op.add_column(sa.Column('batch_id', sa.String, nullable=True))
        batch_op.add_column(sa.Column('message_text', sa.String, nullable=True))


def downgrade():
    with op.batch_alter_table('addjob') as batch_op:
        batch_op.drop_column('message_text')
        batch_op.drop_column('batch_id')
        batch_op.drop_column('allowed_account_ids')
        batch_op.drop_column('kind')
