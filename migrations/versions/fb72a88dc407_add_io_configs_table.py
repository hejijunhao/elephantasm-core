"""add io_configs table

Revision ID: fb72a88dc407
Revises: c873c0d514a9
Create Date: 2025-12-08 22:53:42.470006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fb72a88dc407'
down_revision: Union[str, None] = 'c873c0d514a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create io_configs table for per-anima I/O configuration
    op.create_table('io_configs',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('anima_id', sa.Uuid(), nullable=False),
        sa.Column('read_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('write_settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['anima_id'], ['animas.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_io_configs_anima_id'), 'io_configs', ['anima_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_io_configs_anima_id'), table_name='io_configs')
    op.drop_table('io_configs')
