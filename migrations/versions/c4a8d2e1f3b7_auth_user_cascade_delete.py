"""auth user cascade delete

Add ON DELETE CASCADE/SET NULL to FK chains and create trigger on auth.users
DELETE to cascade-clean public.* data (blocked if user in multi-member org).

Revision ID: c4a8d2e1f3b7
Revises: 7a06e43015b2
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a8d2e1f3b7"
down_revision: Union[str, None] = "7a06e43015b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helper: drop FK then re-create with new ON DELETE behaviour
# ---------------------------------------------------------------------------
def _drop_all_fk_variants(table: str, column: str) -> str:
    """Drop FK constraint regardless of naming convention.

    Some migrations used 'fk_{table}_{column}', others used '{table}_{column}_fkey'.
    Drop both to avoid duplicates.
    """
    return (
        f"ALTER TABLE {table} "
        f"DROP CONSTRAINT IF EXISTS {table}_{column}_fkey;\n"
        f"ALTER TABLE {table} "
        f"DROP CONSTRAINT IF EXISTS fk_{table}_{column};"
    )


def _alter_fk(
    table: str,
    column: str,
    ref_table: str,
    ref_column: str = "id",
    on_delete: str = "CASCADE",
) -> str:
    """Return SQL to drop all FK variants + re-create with new ON DELETE behaviour."""
    constraint = f"{table}_{column}_fkey"
    return (
        f"{_drop_all_fk_variants(table, column)}\n"
        f"ALTER TABLE {table} "
        f"ADD CONSTRAINT {constraint} "
        f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) "
        f"ON DELETE {on_delete};"
    )


def _restore_fk(
    table: str,
    column: str,
    ref_table: str,
    ref_column: str = "id",
) -> str:
    """Return SQL to drop all FK variants + re-create with default (NO ACTION)."""
    constraint = f"{table}_{column}_fkey"
    return (
        f"{_drop_all_fk_variants(table, column)}\n"
        f"ALTER TABLE {table} "
        f"ADD CONSTRAINT {constraint} "
        f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column});"
    )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Phase 1: FK cascade from users downward
    # ------------------------------------------------------------------
    op.execute(_alter_fk("animas", "user_id", "users", on_delete="CASCADE"))
    op.execute(_alter_fk("api_keys", "user_id", "users", on_delete="CASCADE"))
    op.execute(
        _alter_fk("organization_members", "user_id", "users", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("dream_sessions", "triggered_by", "users", on_delete="SET NULL")
    )
    op.execute(
        _alter_fk(
            "subscriptions", "manually_assigned_by", "users", on_delete="SET NULL"
        )
    )
    op.execute(
        _alter_fk("billing_events", "actor_user_id", "users", on_delete="SET NULL")
    )

    # ------------------------------------------------------------------
    # Phase 2: FK cascade from organizations downward
    # ------------------------------------------------------------------
    op.execute(
        _alter_fk("subscriptions", "organization_id", "organizations", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("usage_counters", "organization_id", "organizations", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("usage_periods", "organization_id", "organizations", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("billing_events", "organization_id", "organizations", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("byok_keys", "organization_id", "organizations", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("animas", "organization_id", "organizations", on_delete="SET NULL")
    )
    op.execute(
        _alter_fk(
            "organization_members", "organization_id", "organizations", on_delete="CASCADE"
        )
    )

    # ------------------------------------------------------------------
    # Phase 3: FK cascade from animas downward
    # ------------------------------------------------------------------
    op.execute(_alter_fk("events", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(_alter_fk("memories", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(_alter_fk("knowledge", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(_alter_fk("identities", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(
        _alter_fk("synthesis_configs", "anima_id", "animas", on_delete="CASCADE")
    )
    op.execute(_alter_fk("io_configs", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(_alter_fk("memory_packs", "anima_id", "animas", on_delete="CASCADE"))
    op.execute(_alter_fk("dream_sessions", "anima_id", "animas", on_delete="CASCADE"))

    # ------------------------------------------------------------------
    # Phase 4: FK cascade from knowledge/identities to audit logs
    # ------------------------------------------------------------------
    op.execute(
        _alter_fk("knowledge_audit_log", "knowledge_id", "knowledge", on_delete="CASCADE")
    )
    op.execute(
        _alter_fk("identity_audit_log", "identity_id", "identities", on_delete="CASCADE")
    )

    # Audit log source_memory FKs → SET NULL (don't cascade-delete logs when memories die)
    op.execute(
        _alter_fk(
            "knowledge_audit_log", "source_id", "memories", on_delete="SET NULL"
        )
    )
    op.execute(
        _alter_fk(
            "identity_audit_log", "source_memory_id", "memories", on_delete="SET NULL"
        )
    )

    # ------------------------------------------------------------------
    # Phase 5: Trigger on auth.users DELETE
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_auth_user_deleted()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        SET row_security = off
        AS $$
        DECLARE
            v_user_id UUID;
            v_multi_member_org UUID;
        BEGIN
            -- Find the public.users row
            SELECT id INTO v_user_id
            FROM public.users
            WHERE auth_uid = OLD.id;

            -- If no public user exists, nothing to clean up
            IF v_user_id IS NULL THEN
                RETURN OLD;
            END IF;

            -- Check: does user belong to any org with other members?
            SELECT om.organization_id INTO v_multi_member_org
            FROM public.organization_members om
            WHERE om.organization_id IN (
                SELECT organization_id
                FROM public.organization_members
                WHERE user_id = v_user_id
            )
            AND om.user_id != v_user_id
            LIMIT 1;

            IF v_multi_member_org IS NOT NULL THEN
                RAISE EXCEPTION
                    'Cannot delete user: member of organization % which has other members. '
                    'Transfer ownership or remove user from multi-member orgs first.',
                    v_multi_member_org;
            END IF;

            -- Safe to cascade: delete sole-member orgs first
            -- CASCADE FKs handle subscriptions, usage, billing, byok, org_members
            DELETE FROM public.organizations
            WHERE id IN (
                SELECT organization_id
                FROM public.organization_members
                WHERE user_id = v_user_id
            );

            -- Delete the public user
            -- CASCADE FKs handle animas, api_keys, org_members
            -- Anima CASCADE handles events, memories, knowledge, identity, dreams, packs, etc.
            DELETE FROM public.users WHERE id = v_user_id;

            RETURN OLD;
        END;
        $$;

        CREATE TRIGGER on_auth_user_deleted
            BEFORE DELETE ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_auth_user_deleted();
    """)


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop trigger + function
    # ------------------------------------------------------------------
    op.execute("""
        DROP TRIGGER IF EXISTS on_auth_user_deleted ON auth.users;
        DROP FUNCTION IF EXISTS public.handle_auth_user_deleted();
    """)

    # ------------------------------------------------------------------
    # Restore all FKs to default (NO ACTION / RESTRICT)
    # ------------------------------------------------------------------
    # From users
    op.execute(_restore_fk("animas", "user_id", "users"))
    op.execute(_restore_fk("api_keys", "user_id", "users"))
    op.execute(_restore_fk("organization_members", "user_id", "users"))
    op.execute(_restore_fk("dream_sessions", "triggered_by", "users"))
    op.execute(_restore_fk("subscriptions", "manually_assigned_by", "users"))
    op.execute(_restore_fk("billing_events", "actor_user_id", "users"))

    # From organizations
    op.execute(_restore_fk("subscriptions", "organization_id", "organizations"))
    op.execute(_restore_fk("usage_counters", "organization_id", "organizations"))
    op.execute(_restore_fk("usage_periods", "organization_id", "organizations"))
    op.execute(_restore_fk("billing_events", "organization_id", "organizations"))
    op.execute(_restore_fk("byok_keys", "organization_id", "organizations"))
    op.execute(_restore_fk("animas", "organization_id", "organizations"))
    op.execute(
        _restore_fk("organization_members", "organization_id", "organizations")
    )

    # From animas
    op.execute(_restore_fk("events", "anima_id", "animas"))
    op.execute(_restore_fk("memories", "anima_id", "animas"))
    op.execute(_restore_fk("knowledge", "anima_id", "animas"))
    op.execute(_restore_fk("identities", "anima_id", "animas"))
    op.execute(_restore_fk("synthesis_configs", "anima_id", "animas"))
    op.execute(_restore_fk("io_configs", "anima_id", "animas"))
    op.execute(_restore_fk("memory_packs", "anima_id", "animas"))
    op.execute(_restore_fk("dream_sessions", "anima_id", "animas"))

    # Audit logs
    op.execute(_restore_fk("knowledge_audit_log", "knowledge_id", "knowledge"))
    op.execute(_restore_fk("identity_audit_log", "identity_id", "identities"))
    op.execute(_restore_fk("knowledge_audit_log", "source_id", "memories"))
    op.execute(_restore_fk("identity_audit_log", "source_memory_id", "memories"))
