"""create cron_service role with BYPASSRLS

Revision ID: 7a06e43015b2
Revises: 3dffffc45cb6
Create Date: 2026-03-03 15:18:34.560619

Creates 'cron_service' role for scheduled background jobs.

Purpose:
- BYPASSRLS role for system-level operations (list all animas, stale cleanup)
- Solves: Dreamer and Memory Synthesis schedulers silently processing 0 animas
  because get_db_session() creates sessions without app.current_user, and the
  elephant role (NOBYPASSRLS) returns 0 rows from RLS-protected tables.

Security Model (three tiers):
- postgres role:      Superuser for migrations (bypasses everything)
- elephant role:      App role for API operations (NOBYPASSRLS — RLS enforced)
- cron_service role:  Scheduler role for system jobs (BYPASSRLS — no user context)

Per-anima processing still uses elephant role with get_db_with_rls_context(user_id)
for defense-in-depth. Only system-level queries use cron_service.

IMPORTANT: After running this migration, set password via Supabase dashboard.
    CRON_DATABASE_URL="postgresql://cron_service:<password>@<host>:6543/postgres"
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7a06e43015b2'
down_revision: Union[str, None] = '3dffffc45cb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cron_service role with BYPASSRLS for scheduled jobs."""

    # Step 1: Create cron_service role with BYPASSRLS
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cron_service') THEN
                CREATE ROLE cron_service WITH LOGIN BYPASSRLS;
            END IF;
        END
        $$;
    """)

    # Step 2: Grant database connection
    op.execute("""
        GRANT CONNECT ON DATABASE postgres TO cron_service;
    """)

    # Step 3: Grant schema usage
    op.execute("""
        GRANT USAGE ON SCHEMA public TO cron_service;
    """)

    # Step 4: Grant permissions on all EXISTING objects in public schema
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cron_service;
    """)
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cron_service;
    """)
    op.execute("""
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO cron_service;
    """)

    # Step 5: Grant on app schema (helper functions used by RLS bootstrapping)
    op.execute("""
        GRANT USAGE ON SCHEMA app TO cron_service;
    """)
    op.execute("""
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO cron_service;
    """)

    # Step 6: Auto-grant on future objects created by postgres role
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cron_service;
    """)
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO cron_service;
    """)
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT EXECUTE ON FUNCTIONS TO cron_service;
    """)

    # Step 7: Pin search_path
    op.execute("""
        ALTER ROLE cron_service SET search_path = public, pg_temp;
    """)

    # Step 8: Verify BYPASSRLS is set (safety check)
    op.execute("""
        DO $$
        BEGIN
            IF NOT (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'cron_service') THEN
                RAISE EXCEPTION 'SETUP ERROR: cron_service must have BYPASSRLS';
            END IF;

            IF (SELECT rolsuper FROM pg_roles WHERE rolname = 'cron_service') THEN
                RAISE EXCEPTION 'SECURITY ERROR: cron_service must not be a superuser';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """Remove cron_service role."""

    # Revoke default privileges on future objects
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM cron_service;
    """)
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE USAGE, SELECT ON SEQUENCES FROM cron_service;
    """)
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM cron_service;
    """)

    # Reassign owned objects and drop privileges
    op.execute("""
        REASSIGN OWNED BY cron_service TO postgres;
    """)
    op.execute("""
        DROP OWNED BY cron_service;
    """)

    # Revoke schema and database permissions
    op.execute("""
        REVOKE USAGE ON SCHEMA app FROM cron_service;
    """)
    op.execute("""
        REVOKE USAGE ON SCHEMA public FROM cron_service;
    """)
    op.execute("""
        REVOKE CONNECT ON DATABASE postgres FROM cron_service;
    """)

    # Drop the role
    op.execute("""
        DROP ROLE IF EXISTS cron_service;
    """)
