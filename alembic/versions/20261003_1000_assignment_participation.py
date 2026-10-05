"""assignment is_participation

Revision ID: b3f09d6a2c71
Revises: 8e41c7b2d9a3
Create Date: 2026-10-03 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f09d6a2c71'
down_revision: Union[str, None] = '8e41c7b2d9a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assignments', sa.Column('is_participation', sa.Boolean(), nullable=False,
                                           server_default=sa.false()))
    # Rows uploaded before this existed: mark attendance/participation so they
    # stop asking for a due date. Same rule as app/agent/tools/classify.py.
    op.execute(
        r"""
        UPDATE assignments
        SET is_participation = true, is_category = false
        WHERE title ~* '\m(attendance|participation|engagement|clickers?|iclicker)\M'
           OR title ~* 'in[- ]class activit'
        """
    )


def downgrade() -> None:
    op.drop_column('assignments', 'is_participation')
