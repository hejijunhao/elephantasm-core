"""fix user creation trigger RLS bypass

Revision ID: 17556519dcf7
Revises: c3d4e5f6a7b8
Create Date: 2026-01-13

Problem:
When creating users via Supabase dashboard, the `create_personal_org_for_user()`
trigger function fails because RLS policies on organization_members, subscriptions,
and usage_counters check `app.current_user_id()` which returns NULL during
admin-triggered user creation.

Solution:
Add `SET row_security = off` to the function definition. This works because:
1. The function is SECURITY DEFINER (runs as owner)
2. The owner (postgres) has superuser privileges
3. SET clause in function definition applies during execution

Error seen:
"Database error creating new user" in Supabase dashboard
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '17556519dcf7'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Replace the function with RLS bypass enabled
    op.execute("""
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
        $$ LANGUAGE plpgsql SECURITY DEFINER SET row_security = off;

        COMMENT ON FUNCTION create_personal_org_for_user() IS
        'Auto-creates personal org, membership, subscription, and usage counter when user signs up. RLS bypassed for trigger context.';
    """)


def downgrade() -> None:
    # Restore original function without RLS bypass (will break user creation)
    op.execute("""
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

        COMMENT ON FUNCTION create_personal_org_for_user() IS
        'Auto-creates personal org, membership, subscription, and usage counter when user signs up';
    """)
