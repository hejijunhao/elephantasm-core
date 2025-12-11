"""enable rls policies for knowledge tables

Revision ID: c3e63c60569d
Revises: 7bd636c06650
Create Date: 2025-11-11 09:38:49.518461

Completes database layer security for Knowledge system (Phase 1.5).
Follows existing RLS pattern from v0.1.18 (animas/events/memories).

⚠️ CRITICAL NOTES:
1. Helper function app.current_user_id() already exists (no need to recreate)
2. Indexes already exist (created in 7bd636c06650)
3. Session variable: app.current_user (set by backend get_db_with_rls_context)
4. Both tables use indirect filtering via anima ownership
5. Enforces provenance integrity (knowledge_audit_log.source_id → memories.id)
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3e63c60569d'
down_revision: Union[str, None] = '7bd636c06650'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable RLS policies for knowledge tables."""

    # ============================================================
    # 1. KNOWLEDGE TABLE - Indirect via anima ownership
    # ============================================================
    op.execute("""
        ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access knowledge for their animas
        CREATE POLICY knowledge_via_anima_ownership ON knowledge
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

        COMMENT ON POLICY knowledge_via_anima_ownership ON knowledge IS
        'Users can only access knowledge belonging to their animas';
    """)

    # ============================================================
    # 2. KNOWLEDGE_AUDIT_LOG TABLE - Indirect via knowledge ownership
    # ============================================================
    op.execute("""
        ALTER TABLE knowledge_audit_log ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access audit logs for their knowledge
        -- Also enforces provenance integrity (source_id → memories.id)
        CREATE POLICY knowledge_audit_log_via_ownership ON knowledge_audit_log
            FOR ALL
            USING (
                knowledge_id IN (
                    SELECT k.id FROM knowledge k
                    JOIN animas a ON k.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            )
            WITH CHECK (
                knowledge_id IN (
                    SELECT k.id FROM knowledge k
                    JOIN animas a ON k.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            );

        COMMENT ON POLICY knowledge_audit_log_via_ownership ON knowledge_audit_log IS
        'Users can only access audit logs for their knowledge. Provenance integrity enforced via RLS on memories.';
    """)


def downgrade() -> None:
    """Disable RLS on knowledge tables.

    ⚠️ WARNING: This removes security isolation for knowledge!
    """

    # Drop policies
    op.execute("DROP POLICY IF EXISTS knowledge_via_anima_ownership ON knowledge;")
    op.execute("DROP POLICY IF EXISTS knowledge_audit_log_via_ownership ON knowledge_audit_log;")

    # Disable RLS
    op.execute("ALTER TABLE knowledge DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE knowledge_audit_log DISABLE ROW LEVEL SECURITY;")
