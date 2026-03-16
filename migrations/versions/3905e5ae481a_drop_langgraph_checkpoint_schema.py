"""drop langgraph checkpoint schema

Revision ID: 3905e5ae481a
Revises: ab7de204fb6e
Create Date: 2026-03-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3905e5ae481a'
down_revision: Union[str, None] = 'ab7de204fb6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Drop LangGraph checkpoint schema and all contained tables.

    The langgraph schema was created in revision 54548631fcaa and contained
    tables auto-created by LangGraph's AsyncPostgresSaver:
    - langgraph.checkpoint
    - langgraph.checkpoint_writes
    - langgraph.checkpoint_blobs

    These are no longer needed after migrating workflows to native pipelines.
    Checkpoint data was ephemeral (write-only, never used for recovery).
    """
    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")


def downgrade() -> None:
    """
    Recreate langgraph schema (empty — tables were auto-created by LangGraph).
    """
    op.execute('CREATE SCHEMA IF NOT EXISTS "langgraph"')
    op.execute('ALTER SCHEMA "langgraph" OWNER TO postgres')
    op.execute('GRANT USAGE, CREATE ON SCHEMA "langgraph" TO service_role')
