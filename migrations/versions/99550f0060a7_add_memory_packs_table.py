"""add memory_packs table

Revision ID: 99550f0060a7
Revises: fb72a88dc407
Create Date: 2025-12-08 23:36:44.578858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '99550f0060a7'
down_revision: Union[str, None] = 'fb72a88dc407'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create memory_packs table for persisting compiled memory packs
    op.create_table('memory_packs',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('anima_id', sa.Uuid(), nullable=False),
        sa.Column('query', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('preset_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('session_memory_count', sa.Integer(), nullable=False),
        sa.Column('knowledge_count', sa.Integer(), nullable=False),
        sa.Column('long_term_memory_count', sa.Integer(), nullable=False),
        sa.Column('has_identity', sa.Boolean(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('max_tokens', sa.Integer(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('compiled_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['anima_id'], ['animas.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memory_packs_anima_id'), 'memory_packs', ['anima_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memory_packs_anima_id'), table_name='memory_packs')
    op.drop_table('memory_packs')
