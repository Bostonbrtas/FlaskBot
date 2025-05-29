"""conditionally add archived flags without data loss

Revision ID: 123456abcdef
Revises: <your_previous_revision_id>
Create Date: 2025-05-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '4ed9bec4f51d'
down_revision = 'f0a35e9fbf37'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # === User ===
    result = conn.execute(text('PRAGMA table_info("user")')).fetchall()
    cols = [row[1] for row in result]
    if 'archived' not in cols:
        op.add_column(
            'user',
            sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        conn.execute(text('UPDATE "user" SET archived = 0'))

    # === Project ===
    result = conn.execute(text('PRAGMA table_info("project")')).fetchall()
    cols = [row[1] for row in result]
    if 'archived' not in cols:
        op.add_column(
            'project',
            sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        conn.execute(text('UPDATE "project" SET archived = 0'))

    # === Report ===
    result = conn.execute(text('PRAGMA table_info("report")')).fetchall()
    cols = [row[1] for row in result]
    if 'archived' not in cols:
        op.add_column(
            'report',
            sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        conn.execute(text('UPDATE "report" SET archived = 0'))


def downgrade():
    # SQLite cannot drop columns easily;
    # manual cleanup would be required if you ever downgrade.
    pass