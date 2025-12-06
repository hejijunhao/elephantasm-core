"""configure postgres role search_path for langgraph schema

Revision ID: 0075ef880842
Revises: 2fc126fd07b2
Create Date: 2025-11-03 16:49:43.214932

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0075ef880842'
down_revision: Union[str, None] = '2fc126fd07b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Configure postgres role's default search_path to include langgraph schema.

    Why this is needed:
    - LangGraph checkpoint tables are in langgraph schema (created by migration 54548631fcaa)
    - LangGraph uses unqualified table names (e.g., "CREATE TABLE checkpoints")
    - PostgreSQL resolves unqualified names using search_path
    - pgBouncer transaction mode doesn't support session-level search_path configuration
    - Role-level search_path is inherited by all connections automatically

    This ensures:
    - Checkpoint tables are created in langgraph schema (not public)
    - Both setup (direct connection) and runtime (pgBouncer) find langgraph schema
    - No connection string parameters needed (pgBouncer compatible)

    Related:
    - Migration 54548631fcaa: Creates langgraph schema and grants permissions
    - app/workflows/memory_synthesis/graph.py: LangGraph checkpoint initialization
    """
    # Set role-level default search_path for postgres role
    # This persists across all connections by this role
    op.execute("""
        ALTER ROLE postgres
        SET search_path = langgraph, public, extensions
    """)


def downgrade() -> None:
    """
    Restore postgres role's search_path to original value.

    Note: This resets to the default search_path that existed before this migration.
    If you had a custom search_path before, you'll need to restore it manually.
    """
    # Reset to standard Supabase default search_path
    op.execute("""
        ALTER ROLE postgres
        SET search_path = "$user", public, extensions
    """)

