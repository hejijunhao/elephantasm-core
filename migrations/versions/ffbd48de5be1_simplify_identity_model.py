"""simplify identity model

Revision ID: ffbd48de5be1
Revises: dc050041bb02
Create Date: 2025-12-01 17:47:37.567487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ffbd48de5be1'
down_revision: Union[str, None] = 'dc050041bb02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Simplify Identity model: remove spectrum/assessment columns, add 'self' JSONB
    op.add_column('identities', sa.Column('self', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_column('identities', 'last_assessed_at')
    op.drop_column('identities', 'energy_spectrum')
    op.drop_column('identities', 'description')
    op.drop_column('identities', 'assessment_count')
    op.drop_column('identities', 'decision_patterns')
    op.drop_column('identities', 'decision_spectrum')
    op.drop_column('identities', 'traits')
    op.drop_column('identities', 'information_spectrum')
    op.drop_column('identities', 'confidence')
    op.drop_column('identities', 'lifestyle_spectrum')
    op.drop_column('identities', 'interaction_preferences')


def downgrade() -> None:
    # Restore columns
    op.add_column('identities', sa.Column('interaction_preferences', sa.TEXT(), nullable=True))
    op.add_column('identities', sa.Column('lifestyle_spectrum', sa.DOUBLE_PRECISION(precision=53), nullable=True))
    op.add_column('identities', sa.Column('confidence', sa.DOUBLE_PRECISION(precision=53), nullable=True))
    op.add_column('identities', sa.Column('information_spectrum', sa.DOUBLE_PRECISION(precision=53), nullable=True))
    op.add_column('identities', sa.Column('traits', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('identities', sa.Column('decision_spectrum', sa.DOUBLE_PRECISION(precision=53), nullable=True))
    op.add_column('identities', sa.Column('decision_patterns', sa.TEXT(), nullable=True))
    op.add_column('identities', sa.Column('assessment_count', sa.INTEGER(), nullable=False, server_default='0'))
    op.add_column('identities', sa.Column('description', sa.TEXT(), nullable=True))
    op.add_column('identities', sa.Column('energy_spectrum', sa.DOUBLE_PRECISION(precision=53), nullable=True))
    op.add_column('identities', sa.Column('last_assessed_at', postgresql.TIMESTAMP(), nullable=True))
    op.drop_column('identities', 'self')
