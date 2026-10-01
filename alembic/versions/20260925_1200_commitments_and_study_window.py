"""commitments and study window

Revision ID: 5c2a9e7d41b0
Revises: 1bf23101fe94
Create Date: 2026-09-25 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '5c2a9e7d41b0'
down_revision: Union[str, None] = '1bf23101fe94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('study_start', sa.Time(), nullable=True))
    op.add_column('users', sa.Column('study_end', sa.Time(), nullable=True))
    op.add_column('users', sa.Column('max_hours_per_day', sa.Float(), nullable=True))
    op.create_table(
        'commitments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('course_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='other'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('weekday', sa.Integer(), nullable=True),
        sa.Column('on_date', sa.Date(), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
    )
    op.create_index('ix_commitments_user_id', 'commitments', ['user_id'])
    op.create_index('ix_commitments_course_id', 'commitments', ['course_id'])


def downgrade() -> None:
    op.drop_index('ix_commitments_course_id', table_name='commitments')
    op.drop_index('ix_commitments_user_id', table_name='commitments')
    op.drop_table('commitments')
    op.drop_column('users', 'max_hours_per_day')
    op.drop_column('users', 'study_end')
    op.drop_column('users', 'study_start')
