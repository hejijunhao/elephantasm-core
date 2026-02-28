"""enable rls for identity io_configs and memory_packs tables

Revision ID: a1b2c3d4e5f6
Revises: 3d785f1392f2
Create Date: 2026-01-12

Enables Row-Level Security for 4 tables missing RLS policies:
- identities: via anima ownership
- identity_audit_log: via identity → anima ownership
- io_configs: via anima ownership
- memory_packs: via anima ownership

Follows existing RLS pattern from v0.1.18 (animas/events/memories).
Uses app.current_user_id() helper function (already exists).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3d785f1392f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable RLS policies for identities, identity_audit_log, io_configs, and memory_packs."""

    # ============================================================
    # 1. IDENTITIES TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE identities ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access identities for their animas
        CREATE POLICY identities_via_anima_ownership ON identities
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

        COMMENT ON POLICY identities_via_anima_ownership ON identities IS
        'Users can only access identities belonging to their animas';
    """)

    # ============================================================
    # 2. IDENTITY_AUDIT_LOG TABLE - Indirect via identity → anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE identity_audit_log ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access audit logs for their identities
        CREATE POLICY identity_audit_log_via_ownership ON identity_audit_log
            FOR ALL
            USING (
                identity_id IN (
                    SELECT i.id FROM identities i
                    JOIN animas a ON i.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            )
            WITH CHECK (
                identity_id IN (
                    SELECT i.id FROM identities i
                    JOIN animas a ON i.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            );

        COMMENT ON POLICY identity_audit_log_via_ownership ON identity_audit_log IS
        'Users can only access audit logs for their identities';
    """)

    # ============================================================
    # 3. IO_CONFIGS TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE io_configs ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access io_configs for their animas
        CREATE POLICY io_configs_via_anima_ownership ON io_configs
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

        COMMENT ON POLICY io_configs_via_anima_ownership ON io_configs IS
        'Users can only access io_configs belonging to their animas';
    """)

    # ============================================================
    # 4. MEMORY_PACKS TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE memory_packs ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access memory_packs for their animas
        CREATE POLICY memory_packs_via_anima_ownership ON memory_packs
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

        COMMENT ON POLICY memory_packs_via_anima_ownership ON memory_packs IS
        'Users can only access memory_packs belonging to their animas';
    """)


def downgrade() -> None:
    """Disable RLS on identity, io_config, and memory_pack tables.

    WARNING: This removes security isolation!
    """

    # Drop policies
    op.execute("DROP POLICY IF EXISTS identities_via_anima_ownership ON identities;")
    op.execute("DROP POLICY IF EXISTS identity_audit_log_via_ownership ON identity_audit_log;")
    op.execute("DROP POLICY IF EXISTS io_configs_via_anima_ownership ON io_configs;")
    op.execute("DROP POLICY IF EXISTS memory_packs_via_anima_ownership ON memory_packs;")

    # Disable RLS
    op.execute("ALTER TABLE identities DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE identity_audit_log DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE io_configs DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE memory_packs DISABLE ROW LEVEL SECURITY;")
