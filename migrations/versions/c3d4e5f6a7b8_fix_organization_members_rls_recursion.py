"""fix organization_members RLS infinite recursion

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-01-12

Fixes infinite recursion in organization_members RLS policy.

Problem:
The original policy queried organization_members to check if user can access
organization_members rows, causing infinite recursion:

    SELECT organization_id FROM organization_members
    WHERE user_id = app.current_user_id()

Solution:
1. Create SECURITY DEFINER helper function that bypasses RLS to get user's org_ids
2. Replace recursive policy with one that uses the helper function
3. Users can see:
   - Their own membership rows (direct user_id check)
   - Other members in their organizations (via helper function)
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. CREATE SECURITY DEFINER HELPER FUNCTION
    # ============================================================
    # This function bypasses RLS to get the user's organization IDs
    # without triggering the infinite recursion
    op.execute("""
        CREATE OR REPLACE FUNCTION app.get_user_organization_ids(p_user_id UUID)
        RETURNS SETOF UUID AS $$
            SELECT organization_id
            FROM organization_members
            WHERE user_id = p_user_id
        $$ LANGUAGE sql SECURITY DEFINER STABLE;

        COMMENT ON FUNCTION app.get_user_organization_ids(UUID) IS
        'Returns organization IDs for a user, bypassing RLS to prevent recursion';

        -- Grant execute to elephant role
        GRANT EXECUTE ON FUNCTION app.get_user_organization_ids(UUID) TO elephant;
    """)

    # ============================================================
    # 2. DROP RECURSIVE POLICY ON ORGANIZATION_MEMBERS
    # ============================================================
    op.execute("DROP POLICY IF EXISTS org_members_via_membership ON organization_members;")

    # ============================================================
    # 3. CREATE NON-RECURSIVE POLICY
    # ============================================================
    # Users can see their own rows OR rows in orgs they belong to
    op.execute("""
        CREATE POLICY org_members_access ON organization_members
            FOR ALL
            USING (
                -- Direct check: user can always see their own membership
                user_id = app.current_user_id()
                OR
                -- Indirect check: user can see members of their orgs (via helper)
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                -- For INSERT/UPDATE: user must be member of the org
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY org_members_access ON organization_members IS
        'Users can access their own membership or members of their organizations';
    """)

    # ============================================================
    # 4. UPDATE OTHER POLICIES TO USE HELPER FUNCTION
    # ============================================================
    # These policies also query organization_members and could hit recursion
    # when accessed in same transaction as organization_members

    # Organizations
    op.execute("DROP POLICY IF EXISTS organizations_member_access ON organizations;")
    op.execute("""
        CREATE POLICY organizations_member_access ON organizations
            FOR ALL
            USING (
                id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
                OR NOT is_deleted
            )
            WITH CHECK (
                id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY organizations_member_access ON organizations IS
        'Users can access organizations they are members of';
    """)

    # Subscriptions
    op.execute("DROP POLICY IF EXISTS subscriptions_via_org_membership ON subscriptions;")
    op.execute("""
        CREATE POLICY subscriptions_via_org_membership ON subscriptions
            FOR ALL
            USING (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY subscriptions_via_org_membership ON subscriptions IS
        'Users can access subscriptions for their organizations';
    """)

    # Usage periods
    op.execute("DROP POLICY IF EXISTS usage_periods_via_org_membership ON usage_periods;")
    op.execute("""
        CREATE POLICY usage_periods_via_org_membership ON usage_periods
            FOR ALL
            USING (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY usage_periods_via_org_membership ON usage_periods IS
        'Users can access usage periods for their organizations';
    """)

    # Usage counters
    op.execute("DROP POLICY IF EXISTS usage_counters_via_org_membership ON usage_counters;")
    op.execute("""
        CREATE POLICY usage_counters_via_org_membership ON usage_counters
            FOR ALL
            USING (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY usage_counters_via_org_membership ON usage_counters IS
        'Users can access usage counters for their organizations';
    """)

    # Billing events
    op.execute("DROP POLICY IF EXISTS billing_events_via_org_membership ON billing_events;")
    op.execute("""
        CREATE POLICY billing_events_via_org_membership ON billing_events
            FOR ALL
            USING (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY billing_events_via_org_membership ON billing_events IS
        'Users can access billing events for their organizations';
    """)

    # BYOK keys
    op.execute("DROP POLICY IF EXISTS byok_keys_via_org_membership ON byok_keys;")
    op.execute("""
        CREATE POLICY byok_keys_via_org_membership ON byok_keys
            FOR ALL
            USING (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            )
            WITH CHECK (
                organization_id IN (SELECT app.get_user_organization_ids(app.current_user_id()))
            );

        COMMENT ON POLICY byok_keys_via_org_membership ON byok_keys IS
        'Users can access BYOK keys for their organizations';
    """)


def downgrade() -> None:
    """Revert to original (broken) policies.

    Note: This restores the infinite recursion bug. Only downgrade if
    rolling back the entire pricing infrastructure.
    """

    # Drop fixed policies
    op.execute("DROP POLICY IF EXISTS org_members_access ON organization_members;")
    op.execute("DROP POLICY IF EXISTS organizations_member_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS subscriptions_via_org_membership ON subscriptions;")
    op.execute("DROP POLICY IF EXISTS usage_periods_via_org_membership ON usage_periods;")
    op.execute("DROP POLICY IF EXISTS usage_counters_via_org_membership ON usage_counters;")
    op.execute("DROP POLICY IF EXISTS billing_events_via_org_membership ON billing_events;")
    op.execute("DROP POLICY IF EXISTS byok_keys_via_org_membership ON byok_keys;")

    # Drop helper function
    op.execute("DROP FUNCTION IF EXISTS app.get_user_organization_ids(UUID);")

    # Restore original recursive policy (broken)
    op.execute("""
        CREATE POLICY org_members_via_membership ON organization_members
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    # Restore other original policies
    op.execute("""
        CREATE POLICY organizations_member_access ON organizations
            FOR ALL
            USING (
                id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
                OR NOT is_deleted
            )
            WITH CHECK (
                id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    op.execute("""
        CREATE POLICY subscriptions_via_org_membership ON subscriptions
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    op.execute("""
        CREATE POLICY usage_periods_via_org_membership ON usage_periods
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    op.execute("""
        CREATE POLICY usage_counters_via_org_membership ON usage_counters
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    op.execute("""
        CREATE POLICY billing_events_via_org_membership ON billing_events
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)

    op.execute("""
        CREATE POLICY byok_keys_via_org_membership ON byok_keys
            FOR ALL
            USING (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT organization_id FROM organization_members
                    WHERE user_id = app.current_user_id()
                )
            );
    """)
