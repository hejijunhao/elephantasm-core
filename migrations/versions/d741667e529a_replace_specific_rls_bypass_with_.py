"""replace specific rls bypass with generic entity user lookup

Revision ID: d741667e529a
Revises: 8cf0d923e9b4
Create Date: 2025-11-17 21:06:55.940783

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd741667e529a'
down_revision: Union[str, None] = '8cf0d923e9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Replace specific RLS bypass helper with generic entity user lookup.

    Replaces: public.get_anima_user_id(anima_id UUID)
    With: public.get_entity_user_id(entity_type TEXT, entity_id UUID)

    Generic function supports all entity types:
    - 'anima' → returns animas.user_id
    - 'memory' → returns animas.user_id (via memories.anima_id join)
    - 'event' → returns animas.user_id (via events.anima_id join)
    - 'knowledge' → returns animas.user_id (via knowledge.anima_id join)

    Purpose: Bootstrap RLS context for workflows (chicken-egg problem solver).
    Security: SECURITY DEFINER bypasses RLS but only returns user_id (minimal exposure).
    """
    # Drop old specific function
    op.execute("""
        DROP FUNCTION IF EXISTS public.get_anima_user_id(UUID);
    """)

    # Create new generic function
    op.execute("""
        CREATE OR REPLACE FUNCTION public.get_entity_user_id(
            entity_type text,
            entity_id uuid
        ) RETURNS uuid AS $$
        BEGIN
            CASE entity_type
                WHEN 'anima' THEN
                    RETURN (
                        SELECT user_id
                        FROM animas
                        WHERE id = entity_id
                          AND is_deleted = false
                    );
                WHEN 'memory' THEN
                    RETURN (
                        SELECT a.user_id
                        FROM memories m
                        JOIN animas a ON m.anima_id = a.id
                        WHERE m.id = entity_id
                          AND m.is_deleted = false
                          AND a.is_deleted = false
                    );
                WHEN 'event' THEN
                    RETURN (
                        SELECT a.user_id
                        FROM events e
                        JOIN animas a ON e.anima_id = a.id
                        WHERE e.id = entity_id
                          AND e.is_deleted = false
                          AND a.is_deleted = false
                    );
                WHEN 'knowledge' THEN
                    RETURN (
                        SELECT a.user_id
                        FROM knowledge k
                        JOIN animas a ON k.anima_id = a.id
                        WHERE k.id = entity_id
                          AND k.is_deleted = false
                          AND a.is_deleted = false
                    );
                ELSE
                    RAISE EXCEPTION 'Unknown entity type: %. Valid types: anima, memory, event, knowledge', entity_type;
            END CASE;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Grant execute to elephant role (used by backend runtime)
    op.execute("""
        GRANT EXECUTE ON FUNCTION public.get_entity_user_id(text, uuid) TO elephant;
    """)


def downgrade() -> None:
    """
    Restore original specific function for backward compatibility.
    """
    # Drop generic function
    op.execute("""
        DROP FUNCTION IF EXISTS public.get_entity_user_id(text, uuid);
    """)

    # Restore old specific function
    op.execute("""
        CREATE OR REPLACE FUNCTION public.get_anima_user_id(anima_id uuid)
        RETURNS uuid AS $$
        BEGIN
            RETURN (SELECT user_id FROM animas WHERE id = anima_id);
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    # Grant execute to elephant role
    op.execute("""
        GRANT EXECUTE ON FUNCTION public.get_anima_user_id(uuid) TO elephant;
    """)
