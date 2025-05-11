"""Удалить filepath из project_scan

Revision ID: 60c2dea03746
Revises: 72636e798bc5
Create Date: 2025-05-11 17:42:23.818093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60c2dea03746'
down_revision: Union[str, None] = '72636e798bc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table('project_scan') as batch_op:
        batch_op.drop_column('filepath')

def downgrade():
    with op.batch_alter_table('project_scan') as batch_op:
        batch_op.add_column(sa.Column('filepath', sa.String(255), nullable=False))