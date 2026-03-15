"""add is_internal flag to subscriptions

Revision ID: ab7de204fb6e
Revises: 64804b72cea0
Create Date: 2026-03-14 11:05:07.912716

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ab7de204fb6e'
down_revision: Union[str, None] = '64804b72cea0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('subscriptions', 'is_internal')
