"""assignment done flag

Revision ID: c7a1e4f08b52
Revises: b3f09d6a2c71
Create Date: 2026-10-04 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7a1e4f08b52'
down_revision: Union[str, None] = 'b3f09d6a2c71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assignments', sa.Column('done', sa.Boolean(), nullable=False,
                                           server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('assignments', 'done')
