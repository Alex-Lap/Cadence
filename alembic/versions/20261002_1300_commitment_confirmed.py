"""commitment confirmed flag and note

Revision ID: 8e41c7b2d9a3
Revises: 5c2a9e7d41b0
Create Date: 2026-10-02 13:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8e41c7b2d9a3'
down_revision: Union[str, None] = '5c2a9e7d41b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing commitments were all entered by hand, so they count as confirmed.
    op.add_column('commitments', sa.Column('confirmed', sa.Boolean(), nullable=False,
                                           server_default=sa.true()))
    op.add_column('commitments', sa.Column('note', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('commitments', 'note')
    op.drop_column('commitments', 'confirmed')
