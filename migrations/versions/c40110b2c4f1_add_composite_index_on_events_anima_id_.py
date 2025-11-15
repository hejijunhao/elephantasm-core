"""add composite index on events anima_id occurred_at

Revision ID: c40110b2c4f1
Revises: 0075ef880842
Create Date: 2025-11-05 21:04:01.269559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c40110b2c4f1'
down_revision: Union[str, None] = '0075ef880842'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for COUNT queries used in accumulation score calculation
    # Optimizes EventOperations.count_since() queries filtering by (anima_id, occurred_at)
    op.create_index(
        'ix_events_anima_occurred_at',
        'events',
        ['anima_id', 'occurred_at']
    )


def downgrade() -> None:
    op.drop_index('ix_events_anima_occurred_at', table_name='events')
