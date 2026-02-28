"""add api key validation rls bypass

Revision ID: 2fee1061c5be
Revises: f1a2b3c4d5e6
Create Date: 2026-02-13 07:16:24.322312

Fixes chicken-and-egg: _validate_api_key() needs to read api_keys table,
but RLS requires user_id to be set first. SECURITY DEFINER functions
bypass RLS for the bootstrap lookup and usage recording.

Same pattern used for user auth bootstrap (1e85ffe7ac8a),
workflow RLS bypass (d741667e529a), and org member recursion (c3d4e5f6a7b8).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2fee1061c5be'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. SECURITY DEFINER LOOKUP — bypasses RLS to find API key
    #    candidates by prefix. Returns only fields needed for
    #    bcrypt verification (minimal exposure).
    # ============================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION app.validate_api_key_lookup(p_key_prefix text)
        RETURNS TABLE (
            id uuid,
            user_id uuid,
            key_hash text,
            is_active boolean,
            expires_at timestamp without time zone
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT ak.id, ak.user_id, ak.key_hash::text, ak.is_active, ak.expires_at
            FROM api_keys ak
            WHERE ak.key_prefix = p_key_prefix
              AND ak.is_active = true;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

        REVOKE ALL ON FUNCTION app.validate_api_key_lookup(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.validate_api_key_lookup(text) TO elephant;

        COMMENT ON FUNCTION app.validate_api_key_lookup(text) IS
        'RLS bypass for API key validation bootstrap. Returns candidate keys by prefix for bcrypt verification.';
    """)

    # ============================================================
    # 2. SECURITY DEFINER USAGE RECORDER — bypasses RLS to update
    #    last_used_at and request_count after successful validation.
    # ============================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION app.record_api_key_usage(p_key_id uuid)
        RETURNS void AS $$
        BEGIN
            UPDATE api_keys
            SET last_used_at = now(),
                request_count = request_count + 1
            WHERE id = p_key_id;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;

        REVOKE ALL ON FUNCTION app.record_api_key_usage(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.record_api_key_usage(uuid) TO elephant;

        COMMENT ON FUNCTION app.record_api_key_usage(uuid) IS
        'RLS bypass for recording API key usage stats after successful validation.';
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.record_api_key_usage(uuid);")
    op.execute("DROP FUNCTION IF EXISTS app.validate_api_key_lookup(text);")
