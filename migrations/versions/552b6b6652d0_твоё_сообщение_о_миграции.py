from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy import inspect

# Alembic identifiers
revision = '552b6b6652d0'
down_revision = '0a3855963a04'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("project")]
    fk_names = [fk["name"] for fk in inspector.get_foreign_keys("project")]

    with op.batch_alter_table("project") as batch_op:
        if 'name' not in columns:
            batch_op.add_column(sa.Column('name', sa.String(length=255), nullable=True))

        if 'address' not in columns:
            batch_op.add_column(sa.Column('address', sa.Text(), nullable=True))

        if 'responsible_id' not in columns:
            batch_op.add_column(sa.Column('responsible_id', sa.Integer(), nullable=True))

        if 'fk_project_responsible_id_user' not in fk_names:
            batch_op.create_foreign_key(
                'fk_project_responsible_id_user',
                'user',
                ['responsible_id'],
                ['id']
            )

        for col in ['street', 'city', 'building']:
            if col in columns:
                batch_op.drop_column(col)

def downgrade():
    with op.batch_alter_table("project") as batch_op:
        batch_op.add_column(sa.Column('building', sa.VARCHAR(length=50), nullable=False))
        batch_op.add_column(sa.Column('city', sa.VARCHAR(length=100), nullable=False))
        batch_op.add_column(sa.Column('street', sa.VARCHAR(length=100), nullable=False))
        batch_op.drop_constraint('fk_project_responsible_id_user', type_='foreignkey')
        batch_op.drop_column('responsible_id')
        batch_op.drop_column('address')
        batch_op.drop_column('name')