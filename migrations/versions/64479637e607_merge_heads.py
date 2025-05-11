"""Merge heads

Revision ID: 64479637e607
Revises: 02ea65b6974, 60c2dea03746
Create Date: 2025-05-11 20:23:16.770399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64479637e607'
down_revision: Union[str, None] = ('02ea65b6974', '60c2dea03746')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
