"""Add map_x and map_y columns to memories for UMAP constellation cache

Revision ID: 3b1f4a5c6d7e
Revises: 2a90299c4833
Create Date: 2026-03-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b1f4a5c6d7e"
down_revision: Union[str, None] = "2a90299c4833"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("map_x", sa.Float(), nullable=True))
    op.add_column("memories", sa.Column("map_y", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "map_y")
    op.drop_column("memories", "map_x")
