"""refactor event and memory models

Revision ID: d1575f589a89
Revises: 5d828e895a4c
Create Date: 2025-10-26 14:23:06.540551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1575f589a89'
down_revision: Union[str, None] = '5d828e895a4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Refactor Event and Memory models:
    - Event: Rename meta_summary → summary (safe rename, preserves data)
    - Memory: Add content field + make several fields nullable
    """
    # === Event Model Changes ===
    # CRITICAL: Use rename to preserve data (not drop+add)
    op.alter_column('events', 'meta_summary', new_column_name='summary')

    # === Memory Model Changes ===
    # Add new content field (nullable)
    op.add_column('memories', sa.Column('content', sa.String(), nullable=True))

    # Make existing fields nullable for development flexibility
    op.alter_column('memories', 'summary',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('memories', 'importance',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=True)
    op.alter_column('memories', 'confidence',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=True)
    op.alter_column('memories', 'state',
               existing_type=postgresql.ENUM('ACTIVE', 'DECAYING', 'ARCHIVED', name='memorystate'),
               nullable=True)
    op.alter_column('memories', 'meta',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=True)


def downgrade() -> None:
    """Reverse all changes."""
    # === Reverse Memory Changes ===
    op.alter_column('memories', 'meta',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=False)
    op.alter_column('memories', 'state',
               existing_type=postgresql.ENUM('ACTIVE', 'DECAYING', 'ARCHIVED', name='memorystate'),
               nullable=False)
    op.alter_column('memories', 'confidence',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=False)
    op.alter_column('memories', 'importance',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=False)
    op.alter_column('memories', 'summary',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.drop_column('memories', 'content')

    # === Reverse Event Changes ===
    op.alter_column('events', 'summary', new_column_name='meta_summary')
