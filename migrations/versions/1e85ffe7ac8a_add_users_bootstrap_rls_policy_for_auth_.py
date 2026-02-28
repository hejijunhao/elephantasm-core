"""add users bootstrap rls policy for auth lookup

Revision ID: 1e85ffe7ac8a
Revises: 8b7552d71a08
Create Date: 2025-11-10 12:06:07.402446

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1e85ffe7ac8a'
down_revision: Union[str, None] = '8b7552d71a08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create helper function for auth bootstrap
    # Returns auth_uid from session variable (backend path only)
    op.execute("""
        CREATE OR REPLACE FUNCTION app.effective_uid()
        RETURNS UUID
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$
            SELECT NULLIF(current_setting('app.auth_uid', true), '')::UUID;
        $$;
    """)

    # Grant necessary permissions to elephant role
    # CRITICAL: Without these grants, RLS policy will fail silently
    op.execute("""
        GRANT USAGE ON SCHEMA app TO elephant;
        GRANT EXECUTE ON FUNCTION app.effective_uid() TO elephant;
    """)

    # Create bootstrap RLS policy on users table
    # Allows SELECT by auth_uid before full RLS context is established
    # Solves chicken-egg: need to query users to GET user_id, but RLS requires user_id first
    op.execute("""
        CREATE POLICY users_bootstrap_auth ON public.users
        FOR SELECT
        TO elephant
        USING (auth_uid = app.effective_uid());
    """)

    # Note: Existing users_self_access policy remains for normal operations
    # PostgreSQL OR's policies together, so SELECT works if EITHER passes


def downgrade() -> None:
    # Drop bootstrap policy
    op.execute("DROP POLICY IF EXISTS users_bootstrap_auth ON public.users;")

    # Revoke permissions from elephant role
    op.execute("""
        REVOKE EXECUTE ON FUNCTION app.effective_uid() FROM elephant;
        REVOKE USAGE ON SCHEMA app FROM elephant;
    """)

    # Drop helper function
    op.execute("DROP FUNCTION IF EXISTS app.effective_uid();")

    # Note: Leaves users_self_access policy intact (normal operations)
