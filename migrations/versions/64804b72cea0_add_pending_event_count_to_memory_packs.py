"""add pending_event_count to memory_packs

Revision ID: 64804b72cea0
Revises: c4a8d2e1f3b7
Create Date: 2026-03-09 12:18:50.441863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64804b72cea0'
down_revision: Union[str, None] = 'c4a8d2e1f3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'memory_packs',
        sa.Column('pending_event_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('memory_packs', 'pending_event_count')
