"""Добавлена таблица report_photo и удалено поле photo_path у report"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '02ea65b6974'
down_revision = '72636e798bc5'
branch_labels = None
depends_on = None

def upgrade():
    # на случай, если таблица осталась от прошлых экспериментальных запусков
    op.execute('DROP TABLE IF EXISTS report_photo')

    # создаём новую таблицу для фотографий отчетов
    op.create_table(
        'report_photo',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('report_id', sa.Integer(), sa.ForeignKey('report.id', ondelete='CASCADE'), nullable=False),
        sa.Column('photo_path', sa.String(length=255), nullable=False),
    )

    # и удаляем устаревшее поле в таблице report
    with op.batch_alter_table('report') as batch_op:
        batch_op.drop_column('photo_path')


def downgrade():
    # в откате возвращаем обратно всё как было
    with op.batch_alter_table('report') as batch_op:
        batch_op.add_column(sa.Column('photo_path', sa.String(length=255), nullable=True))

    op.drop_table('report_photo')