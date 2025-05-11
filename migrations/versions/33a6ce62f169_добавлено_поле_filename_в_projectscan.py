"""Добавлено поле filename в ProjectScan

Revision ID: 33a6ce62f169
Revises: 552b6b6652d0
Create Date: 2025-05-11 13:27:53.712859
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33a6ce62f169'
down_revision: Union[str, None] = '552b6b6652d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    with op.batch_alter_table("projectscan") as batch_op:
        batch_op.add_column(sa.Column('filename', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("projectscan") as batch_op:
        batch_op.drop_column('filename')