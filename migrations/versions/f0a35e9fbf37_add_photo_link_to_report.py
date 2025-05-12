"""add photo_link to Report

Revision ID: f0a35e9fbf37
Revises: 64479637e607
Create Date: 2025-05-12 23:03:45.095932
"""

from alembic import op
import sqlalchemy as sa
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'f0a35e9fbf37'
down_revision: Union[str, None] = '64479637e607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('report', sa.Column('photo_link', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('report', 'photo_link')