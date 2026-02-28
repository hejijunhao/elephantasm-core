"""add user auth trigger

Revision ID: 6d97e4d18837
Revises: 41fbe3ecb90a
Create Date: 2025-10-18 14:38:53.995732

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d97e4d18837'
down_revision: Union[str, None] = '41fbe3ecb90a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the handle_new_user() function
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

    # Create the trigger on auth.users table
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW
            EXECUTE FUNCTION public.handle_new_user();
    """)


def downgrade() -> None:
    # Drop trigger first (depends on function)
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;")

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS public.handle_new_user();")
