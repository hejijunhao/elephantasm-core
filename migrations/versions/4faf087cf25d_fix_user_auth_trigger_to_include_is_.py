"""fix user auth trigger to include is_deleted field

Revision ID: 4faf087cf25d
Revises: cec26bf17d4d
Create Date: 2025-10-21 16:06:05.044546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4faf087cf25d'
down_revision: Union[str, None] = 'cec26bf17d4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the existing trigger first
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")

    # Replace the handle_new_user() function with fixed version
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
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
                NEW.id,                    -- auth.users.id → public.users.auth_uid
                NEW.email,                 -- Copy email from auth record
                false,                     -- Default to not deleted
                NOW(),
                NOW()
            )
            ON CONFLICT (auth_uid) DO UPDATE SET
                email = EXCLUDED.email,    -- Update email if changed
                updated_at = NOW();

            RETURN NEW;
        END;
        $$;
    """)

    # Recreate the trigger
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_new_user();
    """)


def downgrade() -> None:
    # Drop the trigger
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")

    # Restore the old version of the function (without is_deleted)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        BEGIN
            -- Create public.users record from auth.users data
            INSERT INTO public.users (
                auth_uid,
                email,
                created_at,
                updated_at
            )
            VALUES (
                NEW.id,                    -- auth.users.id → public.users.auth_uid
                NEW.email,                 -- Copy email from auth record
                NOW(),
                NOW()
            )
            ON CONFLICT (auth_uid) DO UPDATE SET
                email = EXCLUDED.email,    -- Update email if changed
                updated_at = NOW();

            RETURN NEW;
        END;
        $$;
    """)

    # Recreate the trigger
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_new_user();
    """)
