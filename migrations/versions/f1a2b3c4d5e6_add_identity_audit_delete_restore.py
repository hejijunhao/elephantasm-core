"""add DELETE and RESTORE to identityauditaction enum

Revision ID: f1a2b3c4d5e6
Revises: e05ed4ca8053
Create Date: 2026-02-13

Adds DELETE and RESTORE values to the PostgreSQL identityauditaction enum
so identity audit logs correctly record soft-delete and restore operations
instead of incorrectly using UPDATE.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str = "e05ed4ca8053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE identityauditaction ADD VALUE IF NOT EXISTS 'DELETE'")
    op.execute("ALTER TYPE identityauditaction ADD VALUE IF NOT EXISTS 'RESTORE'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from enum types.
    # To downgrade, recreate the type (not automated here).
    pass
