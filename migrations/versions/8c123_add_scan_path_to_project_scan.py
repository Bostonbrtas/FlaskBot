"""Добавлено поле scan_path в project_scan"""

from alembic import op
import sqlalchemy as sa

revision = '8c123'
down_revision = '33a6ce62f169'  # ← сюда подставь актуальный down_revision
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('project_scan') as batch_op:
        batch_op.add_column(sa.Column('scan_path', sa.String(255), nullable=False, server_default=''))

    op.alter_column('project_scan', 'scan_path', server_default=None)

def downgrade():
    with op.batch_alter_table('project_scan') as batch_op:
        batch_op.drop_column('scan_path')