"""create_elephant_application_role

Revision ID: 8b7552d71a08
Revises: d7302645140e
Create Date: 2025-11-09 22:34:29.109218

Creates 'elephant' application role for runtime database operations.

Purpose:
- Non-superuser role that enforces RLS (Row-Level Security) policies
- Separates runtime operations (elephant) from migrations (postgres)
- Ensures multi-tenant isolation is enforced at database level

Security Model:
- postgres role: Superuser for migrations and admin tasks (bypasses RLS)
- elephant role: Application role for API operations (enforces RLS)

Usage:
- Runtime DATABASE_URL: postgresql://elephant:password@host:6543/postgres
- Migration MIGRATION_DATABASE_URL: postgresql://postgres:password@host:5432/postgres

IMPORTANT: After running this migration, update your .env:
    DATABASE_URL="postgresql://elephant:<generated_password>@<host>:6543/postgres"
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8b7552d71a08'
down_revision: Union[str, None] = 'd7302645140e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create elephant application role with RLS-enforced permissions."""

    # NOTE: Password will be set via Supabase dashboard for security
    # This migration creates the role structure; password must be set separately

    # Step 1: Create application role (non-superuser, explicitly forbid BYPASSRLS)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'elephant') THEN
                CREATE ROLE elephant WITH LOGIN NOBYPASSRLS;
            END IF;
        END
        $$;
    """)

    # Step 2: Grant database connection
    op.execute("""
        GRANT CONNECT ON DATABASE postgres TO elephant;
    """)

    # Step 3: Lock down PUBLIC on schema first, then grant precisely to elephant
    # This reduces attack surface by removing default PUBLIC permissions
    op.execute("""
        REVOKE ALL ON SCHEMA public FROM PUBLIC;
    """)

    op.execute("""
        GRANT USAGE ON SCHEMA public TO elephant;
    """)

    # Step 4: Grant permissions on all EXISTING objects in public schema
    # Tables
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO elephant;
    """)

    # Sequences (for auto-increment IDs)
    op.execute("""
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO elephant;
    """)

    # Functions (CRITICAL: includes app.current_user_id() used by RLS policies!)
    op.execute("""
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO elephant;
    """)

    # Step 5: Grant permissions on FUTURE objects created by postgres
    # CRITICAL: Must specify "FOR ROLE postgres" because postgres creates migration objects
    # Without this, future migrations won't auto-grant permissions to elephant

    # Future tables
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO elephant;
    """)

    # Future sequences
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO elephant;
    """)

    # Future functions
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            GRANT EXECUTE ON FUNCTIONS TO elephant;
    """)

    # Step 6: Pin search_path for safer schema resolution
    # Includes pg_temp for standard temporary object handling
    op.execute("""
        ALTER ROLE elephant SET search_path = public, pg_temp;
    """)

    # Step 7: CRITICAL SECURITY CHECKS
    # Verify role is NOT a superuser and does NOT bypass RLS
    # Superusers and BYPASSRLS roles would break multi-tenant isolation
    op.execute("""
        DO $$
        BEGIN
            -- Check not superuser
            IF (SELECT rolsuper FROM pg_roles WHERE rolname = 'elephant') THEN
                RAISE EXCEPTION 'SECURITY ERROR: elephant must not be a superuser (would bypass RLS)';
            END IF;

            -- Check not bypassrls
            IF (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'elephant') THEN
                RAISE EXCEPTION 'SECURITY ERROR: elephant must not BYPASS RLS (would break tenant isolation)';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """Remove elephant application role."""

    # Step 1: Revoke default privileges granted in upgrade
    # These affect future object creation and aren't removed by DROP OWNED
    # Must be done before dropping the role

    # Revoke default privileges on future tables
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM elephant;
    """)

    # Revoke default privileges on future sequences
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE USAGE, SELECT ON SEQUENCES FROM elephant;
    """)

    # Revoke default privileges on future functions
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM elephant;
    """)

    # Step 2: Reassign any objects owned by elephant to postgres
    # This prevents "cannot drop role elephant because some objects depend on it" errors
    op.execute("""
        REASSIGN OWNED BY elephant TO postgres;
    """)

    # Step 3: Drop all explicit privileges granted to elephant
    # This includes grants on existing objects (but not default privileges)
    op.execute("""
        DROP OWNED BY elephant;
    """)

    # Step 4: Revoke schema and database permissions
    op.execute("""
        REVOKE USAGE ON SCHEMA public FROM elephant;
    """)

    op.execute("""
        REVOKE CONNECT ON DATABASE postgres FROM elephant;
    """)

    # Step 5: Restore PUBLIC permissions on schema (reverse Step 3 from upgrade)
    # Note: We only restore USAGE, not CREATE (more secure)
    op.execute("""
        GRANT USAGE ON SCHEMA public TO PUBLIC;
    """)

    # Step 6: Drop the role
    op.execute("""
        DROP ROLE IF EXISTS elephant;
    """)
