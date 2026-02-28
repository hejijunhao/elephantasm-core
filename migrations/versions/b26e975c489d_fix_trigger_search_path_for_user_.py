"""fix trigger search_path for user creation

Revision ID: b26e975c489d
Revises: 17556519dcf7
Create Date: 2026-01-13

Problem:
When creating users via Supabase dashboard, the trigger functions fail with
"relation organizations does not exist" because the search_path doesn't
include the public schema when triggered by Supabase's auth system (GoTrue).

Solution:
Add `SET search_path = public` to both trigger functions to ensure they
can always find the tables regardless of the calling context.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b26e975c489d'
down_revision: Union[str, None] = '17556519dcf7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix handle_new_user function with explicit search_path
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $function$
        BEGIN
            -- Create public.users record from auth.users data
            INSERT INTO public.users (
                auth_uid,
                email,
                is_deleted,
                created_at,
                updated_at
            )
            VALUES (
                NEW.id,
                NEW.email,
                false,
                NOW(),
                NOW()
            )
            ON CONFLICT (auth_uid) DO UPDATE SET
                email = EXCLUDED.email,
                updated_at = NOW();

            RETURN NEW;
        END;
        $function$;

        COMMENT ON FUNCTION public.handle_new_user() IS
        'Creates public.users record when auth.users row is created. Uses explicit search_path for Supabase auth context.';
    """)

    # Fix create_personal_org_for_user function with explicit search_path
    op.execute("""
        CREATE OR REPLACE FUNCTION public.create_personal_org_for_user()
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
            WHILE EXISTS (SELECT 1 FROM public.organizations WHERE slug = final_slug) LOOP
                counter := counter + 1;
                final_slug := base_slug || '-' || counter;
            END LOOP;

            -- Create personal organization
            INSERT INTO public.organizations (name, slug, created_at, updated_at)
            VALUES (
                COALESCE(NEW.first_name || '''s Organization', 'Personal'),
                final_slug,
                NOW(),
                NOW()
            )
            RETURNING id INTO org_id;

            -- Add user as owner
            INSERT INTO public.organization_members (organization_id, user_id, role, created_at, updated_at)
            VALUES (org_id, NEW.id, 'owner', NOW(), NOW());

            -- Create free subscription
            INSERT INTO public.subscriptions (
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
            INSERT INTO public.usage_counters (
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
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public SET row_security = off;

        COMMENT ON FUNCTION public.create_personal_org_for_user() IS
        'Auto-creates personal org, membership, subscription, and usage counter when user signs up. Uses explicit search_path and RLS bypass for trigger context.';
    """)


def downgrade() -> None:
    # Restore handle_new_user without explicit search_path
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $function$
        BEGIN
            INSERT INTO public.users (
                auth_uid,
                email,
                is_deleted,
                created_at,
                updated_at
            )
            VALUES (
                NEW.id,
                NEW.email,
                false,
                NOW(),
                NOW()
            )
            ON CONFLICT (auth_uid) DO UPDATE SET
                email = EXCLUDED.email,
                updated_at = NOW();

            RETURN NEW;
        END;
        $function$;
    """)

    # Restore create_personal_org_for_user without explicit search_path
    op.execute("""
        CREATE OR REPLACE FUNCTION public.create_personal_org_for_user()
        RETURNS TRIGGER AS $$
        DECLARE
            org_id UUID;
            base_slug TEXT;
            final_slug TEXT;
            counter INT := 0;
        BEGIN
            base_slug := COALESCE(
                LOWER(REGEXP_REPLACE(SPLIT_PART(NEW.email, '@', 1), '[^a-z0-9]', '-', 'g')),
                LOWER(SUBSTRING(NEW.auth_uid::TEXT, 1, 8))
            );

            final_slug := base_slug;
            WHILE EXISTS (SELECT 1 FROM organizations WHERE slug = final_slug) LOOP
                counter := counter + 1;
                final_slug := base_slug || '-' || counter;
            END LOOP;

            INSERT INTO organizations (name, slug, created_at, updated_at)
            VALUES (
                COALESCE(NEW.first_name || '''s Organization', 'Personal'),
                final_slug,
                NOW(),
                NOW()
            )
            RETURNING id INTO org_id;

            INSERT INTO organization_members (organization_id, user_id, role, created_at, updated_at)
            VALUES (org_id, NEW.id, 'owner', NOW(), NOW());

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
    """)
