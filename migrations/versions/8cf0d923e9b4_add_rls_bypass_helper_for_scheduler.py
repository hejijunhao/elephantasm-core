"""add rls bypass helper for scheduler

Revision ID: 8cf0d923e9b4
Revises: c3e63c60569d
Create Date: 2025-11-17 16:21:47.646433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cf0d923e9b4'
down_revision: Union[str, None] = 'c3e63c60569d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add SECURITY DEFINER helper for system operations to get anima user_id."""

    op.execute("""
        CREATE FUNCTION public.get_anima_user_id(anima_id uuid)
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER  -- Runs as postgres role (bypasses RLS)
        STABLE           -- Same input = same output (allows optimization)
        AS $$
            SELECT user_id
            FROM public.animas
            WHERE id = anima_id
              AND NOT is_deleted
            LIMIT 1;
        $$;

        GRANT EXECUTE ON FUNCTION public.get_anima_user_id(uuid) TO elephant;

        COMMENT ON FUNCTION public.get_anima_user_id(uuid) IS
            'Get user_id for anima (bypasses RLS). For system operations only.';
    """)


def downgrade() -> None:
    """Remove RLS bypass helper."""
    op.execute("""
        REVOKE EXECUTE ON FUNCTION public.get_anima_user_id(uuid) FROM elephant;
        DROP FUNCTION IF EXISTS public.get_anima_user_id(uuid);
    """)
