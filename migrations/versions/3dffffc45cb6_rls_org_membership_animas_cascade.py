"""rls_org_membership_animas_cascade

Revision ID: 3dffffc45cb6
Revises: 480300cb18d7
Create Date: 2026-02-24 17:54:40.337065

Update RLS policies:
- animas: user_id isolation → org-membership via app.get_user_organization_ids()
- 8 direct anima_id tables: inline user_id check → cascade through animas RLS
- 4 two-hop tables: inline user_id join → cascade through parent table RLS
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3dffffc45cb6'
down_revision: Union[str, None] = '480300cb18d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Old policies (user_id-scoped) for downgrade ---

OLD_ANIMAS = """
    CREATE POLICY animas_user_isolation ON animas FOR ALL
    USING (user_id = app.current_user_id());
"""

OLD_ANIMA_CHILD = """
    CREATE POLICY {policy_name} ON {table} FOR ALL
    USING (anima_id IN (
        SELECT id FROM animas
        WHERE user_id = app.current_user_id() AND NOT is_deleted
    ));
"""

OLD_DREAM_ACTIONS = """
    CREATE POLICY dream_actions_via_session_ownership ON dream_actions FOR ALL
    USING (session_id IN (
        SELECT ds.id FROM dream_sessions ds
        JOIN animas a ON ds.anima_id = a.id
        WHERE a.user_id = app.current_user_id() AND NOT a.is_deleted
    ));
"""

OLD_IDENTITY_AUDIT = """
    CREATE POLICY identity_audit_log_via_ownership ON identity_audit_log FOR ALL
    USING (identity_id IN (
        SELECT i.id FROM identities i
        JOIN animas a ON i.anima_id = a.id
        WHERE a.user_id = app.current_user_id() AND NOT a.is_deleted
    ));
"""

OLD_KNOWLEDGE_AUDIT = """
    CREATE POLICY knowledge_audit_log_via_ownership ON knowledge_audit_log FOR ALL
    USING (knowledge_id IN (
        SELECT k.id FROM knowledge k
        JOIN animas a ON k.anima_id = a.id
        WHERE a.user_id = app.current_user_id() AND NOT a.is_deleted
    ));
"""

OLD_MEMORIES_EVENTS = """
    CREATE POLICY memories_events_via_ownership ON memories_events FOR ALL
    USING (
        memory_id IN (
            SELECT m.id FROM memories m
            JOIN animas a ON m.anima_id = a.id
            WHERE a.user_id = app.current_user_id() AND NOT a.is_deleted
        )
        AND event_id IN (
            SELECT e.id FROM events e
            JOIN animas a ON e.anima_id = a.id
            WHERE a.user_id = app.current_user_id() AND NOT a.is_deleted
        )
    );
"""

# --- Direct anima_id child tables (all follow same pattern) ---

ANIMA_CHILD_TABLES = [
    ("events", "events_via_anima_ownership"),
    ("memories", "memories_via_anima_ownership"),
    ("knowledge", "knowledge_via_anima_ownership"),
    ("identities", "identities_via_anima_ownership"),
    ("io_configs", "io_configs_via_anima_ownership"),
    ("memory_packs", "memory_packs_via_anima_ownership"),
    ("synthesis_configs", "synthesis_configs_via_anima"),
    ("dream_sessions", "dream_sessions_via_anima_ownership"),
]


def upgrade() -> None:
    # ── 1. Animas: user_id → org-membership ──
    op.execute("DROP POLICY IF EXISTS animas_user_isolation ON animas")
    op.execute("""
        CREATE POLICY animas_org_access ON animas FOR ALL
        USING (
            organization_id IN (
                SELECT app.get_user_organization_ids(app.current_user_id())
            )
        )
    """)

    # ── 2. Direct anima_id tables: cascade through animas RLS ──
    for table, old_policy in ANIMA_CHILD_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table}")
        op.execute(f"""
            CREATE POLICY {old_policy} ON {table} FOR ALL
            USING (anima_id IN (SELECT id FROM animas))
        """)

    # ── 3. Two-hop tables: cascade through parent RLS ──

    # dream_actions → dream_sessions (which cascades through animas)
    op.execute("DROP POLICY IF EXISTS dream_actions_via_session_ownership ON dream_actions")
    op.execute("""
        CREATE POLICY dream_actions_via_session_ownership ON dream_actions FOR ALL
        USING (session_id IN (SELECT id FROM dream_sessions))
    """)

    # identity_audit_log → identities (which cascades through animas)
    op.execute("DROP POLICY IF EXISTS identity_audit_log_via_ownership ON identity_audit_log")
    op.execute("""
        CREATE POLICY identity_audit_log_via_ownership ON identity_audit_log FOR ALL
        USING (identity_id IN (SELECT id FROM identities))
    """)

    # knowledge_audit_log → knowledge (which cascades through animas)
    op.execute("DROP POLICY IF EXISTS knowledge_audit_log_via_ownership ON knowledge_audit_log")
    op.execute("""
        CREATE POLICY knowledge_audit_log_via_ownership ON knowledge_audit_log FOR ALL
        USING (knowledge_id IN (SELECT id FROM knowledge))
    """)

    # memories_events → memories + events (both cascade through animas)
    op.execute("DROP POLICY IF EXISTS memories_events_via_ownership ON memories_events")
    op.execute("""
        CREATE POLICY memories_events_via_ownership ON memories_events FOR ALL
        USING (
            memory_id IN (SELECT id FROM memories)
            AND event_id IN (SELECT id FROM events)
        )
    """)


def downgrade() -> None:
    # ── Restore all original user_id-scoped policies ──

    # 1. Animas
    op.execute("DROP POLICY IF EXISTS animas_org_access ON animas")
    op.execute(OLD_ANIMAS)

    # 2. Direct anima_id tables
    for table, policy_name in ANIMA_CHILD_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table}")
        op.execute(OLD_ANIMA_CHILD.format(table=table, policy_name=policy_name))

    # 3. Two-hop tables
    op.execute("DROP POLICY IF EXISTS dream_actions_via_session_ownership ON dream_actions")
    op.execute(OLD_DREAM_ACTIONS)

    op.execute("DROP POLICY IF EXISTS identity_audit_log_via_ownership ON identity_audit_log")
    op.execute(OLD_IDENTITY_AUDIT)

    op.execute("DROP POLICY IF EXISTS knowledge_audit_log_via_ownership ON knowledge_audit_log")
    op.execute(OLD_KNOWLEDGE_AUDIT)

    op.execute("DROP POLICY IF EXISTS memories_events_via_ownership ON memories_events")
    op.execute(OLD_MEMORIES_EVENTS)
