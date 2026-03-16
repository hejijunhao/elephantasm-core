"""add embedding columns to memories and knowledge

Revision ID: c873c0d514a9
Revises: ffbd48de5be1
Create Date: 2025-12-04 08:20:30.685538

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'c873c0d514a9'
down_revision: Union[str, None] = 'ffbd48de5be1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add embedding columns to knowledge table
    op.add_column('knowledge', sa.Column('embedding', Vector(1536), nullable=True))
    op.add_column('knowledge', sa.Column('embedding_model', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True))

    # Add embedding columns to memories table
    op.add_column('memories', sa.Column('embedding', Vector(1536), nullable=True))
    op.add_column('memories', sa.Column('embedding_model', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True))

    # Create IVFFlat indexes for vector similarity search
    op.create_index(
        'ix_memories_embedding',
        'memories',
        ['embedding'],
        postgresql_using='ivfflat',
        postgresql_with={'lists': 100},
        postgresql_ops={'embedding': 'vector_cosine_ops'}
    )

    op.create_index(
        'ix_knowledge_embedding',
        'knowledge',
        ['embedding'],
        postgresql_using='ivfflat',
        postgresql_with={'lists': 100},
        postgresql_ops={'embedding': 'vector_cosine_ops'}
    )


def downgrade() -> None:
    # Drop indexes first
    op.drop_index('ix_knowledge_embedding', table_name='knowledge')
    op.drop_index('ix_memories_embedding', table_name='memories')

    # Drop columns
    op.drop_column('memories', 'embedding_model')
    op.drop_column('memories', 'embedding')
    op.drop_column('knowledge', 'embedding_model')
    op.drop_column('knowledge', 'embedding')
