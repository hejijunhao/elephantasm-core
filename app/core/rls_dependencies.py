"""
RLS (Row-Level Security) FastAPI dependencies.

Provides database session dependencies with automatic RLS context injection.
"""

from typing import Generator, Optional
from uuid import UUID
from fastapi import Depends
from sqlmodel import Session
from sqlalchemy import text

from app.core.database import get_db_with_rls_context
from app.core.auth import require_current_user_id


async def get_db_with_rls(
    user_id: UUID = Depends(require_current_user_id)
) -> Generator[Session, None, None]:
    """
    Database session with automatic RLS context from JWT or API key.

    This is the PRIMARY database dependency for authenticated API routes.
    Rejects unauthenticated requests with 401 (via require_current_user_id).

    How it works:
        1. require_current_user_id extracts user_id from JWT/API key (401 on failure)
        2. get_db_with_rls_context creates session and sets app.current_user variable
        3. All queries automatically filtered by RLS policies
        4. Session commits on success, rolls back on error
    """
    with get_db_with_rls_context(user_id) as db:
        yield db


def get_entity_user_id_bypass_rls(
    session: Session,
    entity_type: str,
    entity_id: UUID,
) -> Optional[UUID]:
    """
    Get user_id for any entity, bypassing RLS.

    SECURITY: Uses public.get_entity_user_id() SECURITY DEFINER function.
    ONLY use for system operations (schedulers, background jobs, workflows).

    This function exists to solve the RLS circular dependency:
    - Workflows need user_id to set RLS context
    - Must read entity to get anima_id, then anima.user_id
    - But RLS blocks read (requires user_id)
    - STUCK (circular)

    Solution: PostgreSQL SECURITY DEFINER function bypasses RLS for ownership
    lookup only. Function only returns user_id (minimal exposure).

    Supported entity types:
    - 'anima': Direct user_id lookup (animas.user_id)
    - 'memory': Via join (memories.anima_id → animas.user_id)
    - 'event': Via join (events.anima_id → animas.user_id)
    - 'knowledge': Via join (knowledge.anima_id → animas.user_id)

    Args:
        session: Database session
        entity_type: Entity type ('anima', 'memory', 'event', 'knowledge')
        entity_id: Entity UUID

    Returns:
        User UUID if entity exists and not deleted, None otherwise

    Raises:
        DatabaseError: If entity_type is invalid (from PostgreSQL)

    Example:
        # Memory Synthesis (has anima_id)
        user_id = get_entity_user_id_bypass_rls(session, 'anima', anima_id)

        # Knowledge Synthesis (has memory_id)
        user_id = get_entity_user_id_bypass_rls(session, 'memory', memory_id)
    """
    # Use session.execute() for raw SQL (not session.exec())
    result = session.execute(
        text("SELECT public.get_entity_user_id(:entity_type, :entity_id)"),
        {"entity_type": entity_type, "entity_id": str(entity_id)},
    ).scalar_one_or_none()

    # result is already a UUID (from psycopg adapter) or None
    return result
