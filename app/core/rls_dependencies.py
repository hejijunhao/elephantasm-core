"""
RLS (Row-Level Security) FastAPI dependencies.

Provides database session dependencies with automatic RLS context injection.
"""

from typing import Generator
from uuid import UUID
from fastapi import Depends
from sqlmodel import Session

from app.core.database import get_db_with_rls_context
from app.core.auth import get_current_user_id


async def get_db_with_rls(
    user_id: UUID | None = Depends(get_current_user_id)
) -> Generator[Session, None, None]:
    """
    Database session with automatic RLS context from JWT.

    This is the PRIMARY database dependency for authenticated API routes.
    Automatically extracts user_id from JWT and sets RLS context.

    Usage:
        @router.get("/animas")
        async def list_animas(db: Session = Depends(get_db_with_rls)):
            # Automatically filtered by user_id via RLS policies
            animas = AnimaOperations.get_all(db)
            return animas

    How it works:
        1. get_current_user_id extracts user_id from JWT Authorization header
        2. get_db_with_rls_context creates session and sets app.current_user variable
        3. All queries automatically filtered by RLS policies
        4. Session commits on success, rolls back on error

    ⚠️ CRITICAL: RLS policies enforce multi-tenant isolation.
    Without proper user_id, queries return empty results (not errors).
    """
    # Delegate to internal function with user_id (sync generator)
    for db in get_db_with_rls_context(user_id):
        yield db
