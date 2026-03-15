"""add pricing infrastructure phase 1

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-12

Phase 1 of pricing infrastructure: Database Foundation

Creates tables:
- organizations: Multi-tenant billing entities
- organization_members: User-to-org membership with roles
- subscriptions: Plan subscriptions tied to organizations
- usage_periods: Historical billing period snapshots
- usage_counters: Real-time usage tracking
- billing_events: Audit log for billing events
- byok_keys: Encrypted customer API key storage

Adds columns to animas:
- is_dormant: Boolean flag for inactive animas (30+ days)
- last_activity_at: Timestamp of last event/pack activity

Creates triggers:
- Auto-create personal org + subscription when user signs up
- Backfill existing users with personal orgs

Enables RLS policies for all new tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. ORGANIZATIONS TABLE
    # ============================================================
    op.create_table('organizations',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_organizations_name', 'organizations', ['name'], unique=False)
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    # ============================================================
    # 2. ORGANIZATION_MEMBERS TABLE
    # ============================================================
    op.create_table('organization_members',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='member'),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_member')
    )
    op.create_index('ix_organization_members_organization_id', 'organization_members', ['organization_id'], unique=False)
    op.create_index('ix_organization_members_user_id', 'organization_members', ['user_id'], unique=False)

    # ============================================================
    # 3. SUBSCRIPTIONS TABLE
    # ============================================================
    op.create_table('subscriptions',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('plan_tier', sa.String(length=50), nullable=False, server_default='free'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('current_period_start', sa.DateTime(), nullable=False),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_metered_item_id', sa.String(length=255), nullable=True),
        sa.Column('spending_cap_cents', sa.Integer(), nullable=False, server_default='-1'),
        sa.Column('is_manually_assigned', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('manually_assigned_by', sa.Uuid(), nullable=True),
        sa.Column('manually_assigned_at', sa.DateTime(), nullable=True),
        sa.Column('manual_assignment_note', sa.Text(), nullable=True),
        sa.Column('byok_openai_key_set', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('byok_anthropic_key_set', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['manually_assigned_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subscriptions_organization_id', 'subscriptions', ['organization_id'], unique=True)
    op.create_index('ix_subscriptions_plan_tier', 'subscriptions', ['plan_tier'], unique=False)
    op.create_index('ix_subscriptions_stripe_customer_id', 'subscriptions', ['stripe_customer_id'], unique=False)
    op.create_index('ix_subscriptions_stripe_subscription_id', 'subscriptions', ['stripe_subscription_id'], unique=False)

    # ============================================================
    # 4. USAGE_PERIODS TABLE (Historical snapshots)
    # ============================================================
    op.create_table('usage_periods',
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('plan_tier', sa.String(length=50), nullable=False),
        sa.Column('active_anima_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dormant_anima_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('events_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('memories_stored', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('knowledge_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pack_builds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synthesis_runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vector_storage_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('overage_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_billed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('billed_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'period_start', name='uq_usage_period_org_start')
    )
    op.create_index('ix_usage_periods_organization_id', 'usage_periods', ['organization_id'], unique=False)

    # ============================================================
    # 5. USAGE_COUNTERS TABLE (Real-time counters)
    # ============================================================
    op.create_table('usage_counters',
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('events_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pack_builds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synthesis_runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('memories_stored', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('knowledge_items', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vector_storage_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('active_anima_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dormant_anima_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_anima_check', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_usage_counters_organization_id', 'usage_counters', ['organization_id'], unique=True)

    # ============================================================
    # 6. BILLING_EVENTS TABLE (Audit log)
    # ============================================================
    op.create_table('billing_events',
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('previous_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('stripe_event_id', sa.String(length=255), nullable=True),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_billing_events_organization_id', 'billing_events', ['organization_id'], unique=False)
    op.create_index('ix_billing_events_event_type', 'billing_events', ['event_type'], unique=False)
    op.create_index('ix_billing_events_stripe_event_id', 'billing_events', ['stripe_event_id'], unique=False)

    # ============================================================
    # 7. BYOK_KEYS TABLE (Encrypted customer API keys)
    # ============================================================
    op.create_table('byok_keys',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('key_prefix', sa.String(length=20), nullable=False),
        sa.Column('encrypted_key', sa.Text(), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'provider', name='uq_byok_org_provider')
    )
    op.create_index('ix_byok_keys_organization_id', 'byok_keys', ['organization_id'], unique=False)

    # ============================================================
    # 8. ADD DORMANCY COLUMNS TO ANIMAS
    # ============================================================
    op.add_column('animas', sa.Column('is_dormant', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('animas', sa.Column('last_activity_at', sa.DateTime(), nullable=True))
    op.create_index('ix_animas_is_dormant', 'animas', ['is_dormant'], unique=False)

    # ============================================================
    # 9. RLS POLICIES FOR NEW TABLES
    # ============================================================

    # Organizations - users can see orgs they're members of
    op.execute("""
        ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY organizations_member_access ON organizations IS
        'Users can access organizations they are members of';
    """)

    # Organization members - users can see members of their orgs
    op.execute("""
        ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY org_members_via_membership ON organization_members IS
        'Users can access members of organizations they belong to';
    """)

    # Subscriptions - users can see subscriptions for their orgs
    op.execute("""
        ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY subscriptions_via_org_membership ON subscriptions IS
        'Users can access subscriptions for their organizations';
    """)

    # Usage periods - users can see usage for their orgs
    op.execute("""
        ALTER TABLE usage_periods ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY usage_periods_via_org_membership ON usage_periods IS
        'Users can access usage periods for their organizations';
    """)

    # Usage counters - users can see counters for their orgs
    op.execute("""
        ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY usage_counters_via_org_membership ON usage_counters IS
        'Users can access usage counters for their organizations';
    """)

    # Billing events - users can see billing events for their orgs
    op.execute("""
        ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY billing_events_via_org_membership ON billing_events IS
        'Users can access billing events for their organizations';
    """)

    # BYOK keys - users can access keys for their orgs
    op.execute("""
        ALTER TABLE byok_keys ENABLE ROW LEVEL SECURITY;

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

        COMMENT ON POLICY byok_keys_via_org_membership ON byok_keys IS
        'Users can access BYOK keys for their organizations';
    """)

    # ============================================================
    # 10. AUTO-PROVISIONING TRIGGER FOR NEW USERS
    # ============================================================
    op.execute("""
        -- Function to create personal org + subscription when user is created
        CREATE OR REPLACE FUNCTION create_personal_org_for_user()
        RETURNS TRIGGER AS $$
        DECLARE
            org_id UUID;
            base_slug TEXT;
            final_slug TEXT;
            counter INT := 0;
        BEGIN
            -- Generate base slug from email or auth_uid
            base_slug := COALESCE(
                LOWER(REGEXP_REPLACE(SPLIT_PART(NEW.email, '@', 1), '[^a-z0-9]', '-', 'g')),
                LOWER(SUBSTRING(NEW.auth_uid::TEXT, 1, 8))
            );

            -- Find unique slug (append -1, -2, etc. if needed)
            final_slug := base_slug;
            WHILE EXISTS (SELECT 1 FROM organizations WHERE slug = final_slug) LOOP
                counter := counter + 1;
                final_slug := base_slug || '-' || counter;
            END LOOP;

            -- Create personal organization
            INSERT INTO organizations (name, slug, created_at, updated_at)
            VALUES (
                COALESCE(NEW.first_name || '''s Organization', 'Personal'),
                final_slug,
                NOW(),
                NOW()
            )
            RETURNING id INTO org_id;

            -- Add user as owner
            INSERT INTO organization_members (organization_id, user_id, role, created_at, updated_at)
            VALUES (org_id, NEW.id, 'owner', NOW(), NOW());

            -- Create free subscription
            INSERT INTO subscriptions (
                organization_id,
                plan_tier,
                status,
                current_period_start,
                current_period_end,
                created_at,
                updated_at
            )
            VALUES (
                org_id,
                'free',
                'active',
                DATE_TRUNC('month', NOW()),
                DATE_TRUNC('month', NOW()) + INTERVAL '1 month',
                NOW(),
                NOW()
            );

            -- Initialize usage counter
            INSERT INTO usage_counters (
                organization_id,
                period_start,
                last_anima_check,
                updated_at
            )
            VALUES (
                org_id,
                CURRENT_DATE,
                NOW(),
                NOW()
            );

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;

        -- Drop existing trigger if it exists (for idempotency)
        DROP TRIGGER IF EXISTS trg_create_personal_org ON users;

        -- Create trigger on user insert
        CREATE TRIGGER trg_create_personal_org
            AFTER INSERT ON users
            FOR EACH ROW
            EXECUTE FUNCTION create_personal_org_for_user();

        COMMENT ON FUNCTION create_personal_org_for_user() IS
        'Auto-creates personal org, membership, subscription, and usage counter when user signs up';
    """)

    # ============================================================
    # 11. BACKFILL EXISTING USERS WITH PERSONAL ORGS
    # ============================================================
    op.execute("""
        -- Backfill: Create orgs for existing users who don't have one
        DO $$
        DECLARE
            user_rec RECORD;
            org_id UUID;
            base_slug TEXT;
            final_slug TEXT;
            counter INT;
        BEGIN
            FOR user_rec IN
                SELECT u.id, u.email, u.first_name, u.auth_uid
                FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM organization_members om WHERE om.user_id = u.id
                )
                AND NOT u.is_deleted
            LOOP
                counter := 0;

                -- Generate base slug
                base_slug := COALESCE(
                    LOWER(REGEXP_REPLACE(SPLIT_PART(user_rec.email, '@', 1), '[^a-z0-9]', '-', 'g')),
                    LOWER(SUBSTRING(user_rec.auth_uid::TEXT, 1, 8))
                );

                -- Find unique slug
                final_slug := base_slug;
                WHILE EXISTS (SELECT 1 FROM organizations WHERE slug = final_slug) LOOP
                    counter := counter + 1;
                    final_slug := base_slug || '-' || counter;
                END LOOP;

                -- Create org
                INSERT INTO organizations (name, slug, created_at, updated_at)
                VALUES (
                    COALESCE(user_rec.first_name || '''s Organization', 'Personal'),
                    final_slug,
                    NOW(),
                    NOW()
                )
                RETURNING id INTO org_id;

                -- Add membership
                INSERT INTO organization_members (organization_id, user_id, role, created_at, updated_at)
                VALUES (org_id, user_rec.id, 'owner', NOW(), NOW());

                -- Create subscription
                INSERT INTO subscriptions (
                    organization_id, plan_tier, status,
                    current_period_start, current_period_end,
                    created_at, updated_at
                )
                VALUES (
                    org_id, 'free', 'active',
                    DATE_TRUNC('month', NOW()),
                    DATE_TRUNC('month', NOW()) + INTERVAL '1 month',
                    NOW(), NOW()
                );

                -- Create usage counter
                INSERT INTO usage_counters (
                    organization_id, period_start, last_anima_check, updated_at
                )
                VALUES (org_id, CURRENT_DATE, NOW(), NOW());
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    """Remove pricing infrastructure.

    WARNING: This removes organization structure, subscriptions, and billing data!
    """

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_create_personal_org ON users;")
    op.execute("DROP FUNCTION IF EXISTS create_personal_org_for_user();")

    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS organizations_member_access ON organizations;")
    op.execute("DROP POLICY IF EXISTS org_members_via_membership ON organization_members;")
    op.execute("DROP POLICY IF EXISTS subscriptions_via_org_membership ON subscriptions;")
    op.execute("DROP POLICY IF EXISTS usage_periods_via_org_membership ON usage_periods;")
    op.execute("DROP POLICY IF EXISTS usage_counters_via_org_membership ON usage_counters;")
    op.execute("DROP POLICY IF EXISTS billing_events_via_org_membership ON billing_events;")
    op.execute("DROP POLICY IF EXISTS byok_keys_via_org_membership ON byok_keys;")

    # Disable RLS
    op.execute("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE organization_members DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE subscriptions DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE usage_periods DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE usage_counters DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE billing_events DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE byok_keys DISABLE ROW LEVEL SECURITY;")

    # Drop indexes on animas
    op.drop_index('ix_animas_is_dormant', table_name='animas')

    # Drop columns from animas
    op.drop_column('animas', 'last_activity_at')
    op.drop_column('animas', 'is_dormant')

    # Drop tables in reverse dependency order
    op.drop_index('ix_byok_keys_organization_id', table_name='byok_keys')
    op.drop_table('byok_keys')

    op.drop_index('ix_billing_events_stripe_event_id', table_name='billing_events')
    op.drop_index('ix_billing_events_event_type', table_name='billing_events')
    op.drop_index('ix_billing_events_organization_id', table_name='billing_events')
    op.drop_table('billing_events')

    op.drop_index('ix_usage_counters_organization_id', table_name='usage_counters')
    op.drop_table('usage_counters')

    op.drop_index('ix_usage_periods_organization_id', table_name='usage_periods')
    op.drop_table('usage_periods')

    op.drop_index('ix_subscriptions_stripe_subscription_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_stripe_customer_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_plan_tier', table_name='subscriptions')
    op.drop_index('ix_subscriptions_organization_id', table_name='subscriptions')
    op.drop_table('subscriptions')

    op.drop_index('ix_organization_members_user_id', table_name='organization_members')
    op.drop_index('ix_organization_members_organization_id', table_name='organization_members')
    op.drop_table('organization_members')

    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.drop_index('ix_organizations_name', table_name='organizations')
    op.drop_table('organizations')
