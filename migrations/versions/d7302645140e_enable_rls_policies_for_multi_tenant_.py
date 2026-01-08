"""enable rls policies for multi-tenant isolation

Revision ID: d7302645140e
Revises: 9d0eaf1d64c1
Create Date: 2025-11-08 17:56:55.042693

⚠️ CRITICAL NOTES:
1. Service role bypasses RLS (backend uses service role by default)
2. Must set session variables manually OR use anon key
3. Session variables must use SET LOCAL (transaction-scoped)
4. Helper function app.current_user_id() returns user.id from session variable
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd7302645140e'
down_revision: Union[str, None] = '9d0eaf1d64c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable RLS and create isolation policies."""

    # ============================================================
    # HELPER FUNCTION: Get user.id from session variable
    # ============================================================
    op.execute("""
        -- Create schema if not exists
        CREATE SCHEMA IF NOT EXISTS app;

        -- Create function to get current user.id from session variable
        -- Session variable stores user.id as text (set by backend)
        CREATE OR REPLACE FUNCTION app.current_user_id()
        RETURNS uuid AS $$
        BEGIN
            RETURN current_setting('app.current_user', true)::uuid;
        EXCEPTION
            WHEN OTHERS THEN
                RETURN NULL;  -- Return NULL if variable not set
        END;
        $$ LANGUAGE plpgsql STABLE;

        COMMENT ON FUNCTION app.current_user_id() IS
        'Returns current user.id from session variable app.current_user. Returns NULL if not set.';
    """)

    # ============================================================
    # 1. USERS TABLE - Self-access only
    # ============================================================
    op.execute("""
        ALTER TABLE users ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access their own user record
        CREATE POLICY users_self_access ON users
            FOR ALL
            USING (id = app.current_user_id())
            WITH CHECK (id = app.current_user_id());

        COMMENT ON POLICY users_self_access ON users IS
        'Users can only SELECT/UPDATE/DELETE their own user record';
    """)

    # ============================================================
    # 2. ANIMAS TABLE - Direct user_id filtering
    # ============================================================
    op.execute("""
        ALTER TABLE animas ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access animas they own
        CREATE POLICY animas_user_isolation ON animas
            FOR ALL
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());

        COMMENT ON POLICY animas_user_isolation ON animas IS
        'Users can only access animas where user_id matches current user';
    """)

    # ============================================================
    # 3. EVENTS TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE events ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access events for their animas
        CREATE POLICY events_via_anima_ownership ON events
            FOR ALL
            USING (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            )
            WITH CHECK (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            );

        COMMENT ON POLICY events_via_anima_ownership ON events IS
        'Users can only access events belonging to their animas';
    """)

    # ============================================================
    # 4. MEMORIES TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE memories ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access memories for their animas
        CREATE POLICY memories_via_anima_ownership ON memories
            FOR ALL
            USING (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            )
            WITH CHECK (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            );

        COMMENT ON POLICY memories_via_anima_ownership ON memories IS
        'Users can only access memories belonging to their animas';
    """)

    # ============================================================
    # 5. MEMORIES_EVENTS TABLE - Indirect via both FKs
    # ============================================================
    op.execute("""
        ALTER TABLE memories_events ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access links for their memories/events
        CREATE POLICY memories_events_via_ownership ON memories_events
            FOR ALL
            USING (
                -- Both memory and event must belong to user's animas
                memory_id IN (
                    SELECT m.id FROM memories m
                    JOIN animas a ON m.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
                AND
                event_id IN (
                    SELECT e.id FROM events e
                    JOIN animas a ON e.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            )
            WITH CHECK (
                memory_id IN (
                    SELECT m.id FROM memories m
                    JOIN animas a ON m.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
                AND
                event_id IN (
                    SELECT e.id FROM events e
                    JOIN animas a ON e.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            );

        COMMENT ON POLICY memories_events_via_ownership ON memories_events IS
        'Users can only access memory-event links for their own data';
    """)

    # ============================================================
    # 6. SYNTHESIS_CONFIGS TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE synthesis_configs ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access configs for their animas
        CREATE POLICY synthesis_configs_via_anima ON synthesis_configs
            FOR ALL
            USING (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            )
            WITH CHECK (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            );

        COMMENT ON POLICY synthesis_configs_via_anima ON synthesis_configs IS
        'Users can only access synthesis configs for their animas';
    """)


def downgrade() -> None:
    """Disable RLS and remove policies.

    ⚠️ WARNING: This removes ALL security isolation!
    """

    # Drop policies
    op.execute("DROP POLICY IF EXISTS users_self_access ON users;")
    op.execute("DROP POLICY IF EXISTS animas_user_isolation ON animas;")
    op.execute("DROP POLICY IF EXISTS events_via_anima_ownership ON events;")
    op.execute("DROP POLICY IF EXISTS memories_via_anima_ownership ON memories;")
    op.execute("DROP POLICY IF EXISTS memories_events_via_ownership ON memories_events;")
    op.execute("DROP POLICY IF EXISTS synthesis_configs_via_anima ON synthesis_configs;")

    # Disable RLS
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE animas DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE events DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE memories DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE memories_events DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE synthesis_configs DISABLE ROW LEVEL SECURITY;")

    # Drop helper function
    op.execute("DROP FUNCTION IF EXISTS app.current_user_id();")

    # Drop schema if empty
    op.execute("DROP SCHEMA IF EXISTS app CASCADE;")
