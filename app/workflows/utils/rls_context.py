"""
RLS Context Management for LangGraph Workflows

Utilities for setting Row-Level Security (RLS) context in workflow nodes.
Workflows are user-triggered and must enforce multi-tenant isolation.

Design Philosophy:
- Every workflow operation has user context (from anima.user_id)
- All database operations in workflows MUST use RLS context
- Even if workflow has bug, RLS prevents cross-user data leaks
- Consistent security model across API endpoints and workflows

⚠️ CRITICAL: Never use admin/service connections for user-triggered workflows!
Background jobs triggered by users must operate within user's security context.
"""

from contextlib import contextmanager
from typing import Generator
from uuid import UUID
from sqlalchemy import text
from sqlmodel import Session

from app.core.database import SessionLocal
from app.models.database.animas import Anima


def get_user_id_for_anima(anima_id: UUID) -> UUID:
    """
    Get user_id for anima (for setting RLS context).

    ⚠️ Uses separate session (service role, no RLS).
    Must be called BEFORE setting RLS context.

    This lookup is safe without RLS because:
    - Used only for setting RLS context (not returning data to user)
    - Workflow already triggered by authenticated user for this anima
    - RLS will be enforced on all subsequent operations

    Args:
        anima_id: Anima UUID

    Returns:
        User UUID

    Raises:
        ValueError: If anima not found or has no user

    Example:
        user_id = get_user_id_for_anima(anima_id)
        with session_with_rls_context(user_id) as session:
            # All operations here filtered by user_id
            memory = MemoryOperations.create(session, data)
    """
    # Import bypass helper to avoid RLS chicken-egg problem
    from app.core.rls_dependencies import get_entity_user_id_bypass_rls

    with SessionLocal() as session:
        # Use SECURITY DEFINER helper to bypass RLS for this lookup
        # (can't query animas table without RLS context, but need user_id to set context)
        user_id = get_entity_user_id_bypass_rls(session, 'anima', anima_id)
        if not user_id:
            raise ValueError(f"Anima {anima_id} not found")
        return user_id


@contextmanager
def session_with_rls_context(user_id: UUID) -> Generator[Session, None, None]:
    """
    Context manager for database session with RLS context.

    Sets PostgreSQL session variable 'app.current_user' which RLS policies
    use to filter queries. All database operations in this session are
    automatically filtered to only show data owned by this user.

    Usage Pattern (Atomic Transaction):
        user_id = get_user_id_for_anima(anima_id)

        with session_with_rls_context(user_id) as session:
            # Create memory
            memory = MemoryOperations.create(session, data)
            session.flush()  # ✅ Persist but keep transaction open

            # Create provenance links (same transaction = atomic)
            links = MemoryEventOperations.bulk_create(session, links)
            session.flush()

            # Auto-commit on context exit (all-or-nothing)

    ⚠️ IMPORTANT: Use flush() between operations, not commit()!
    - flush() persists to DB but keeps transaction open
    - commit() would clear session variables in pgBouncer
    - All operations in one context = single atomic transaction

    Architecture Benefits:
    1. **Atomicity**: Memory + links created together (proper ACID)
    2. **RLS Context**: user_id set once for entire operation
    3. **Security**: Even if workflow has bug, RLS prevents cross-user access
    4. **Data Integrity**: No orphaned memories or links possible

    Args:
        user_id: User UUID for RLS context

    Yields:
        Session with RLS context set

    Raises:
        Exception: Any database errors (rolls back entire transaction)

    Technical Details:
    - Session variable: 'app.current_user' (read by RLS policies)
    - Scope: Transaction-scoped (SET LOCAL, auto-resets)
    - pgBouncer safe: SET LOCAL is transaction-scoped, not connection-scoped
    - Service role: Backend uses service role, so we set session vars manually
    """
    session = SessionLocal()
    try:
        # Set RLS context (transaction-scoped)
        # Store as text, policies cast to UUID
        # Note: We quote "app.current_user" because current_user is a PostgreSQL reserved keyword
        session.execute(
            text(f"SET LOCAL \"app.current_user\" = '{str(user_id)}'")
        )

        yield session

        # Commit entire transaction on success
        # All flush() operations persist atomically
        session.commit()

    except Exception:
        # Rollback all flush() operations on any error
        session.rollback()
        raise
    finally:
        # Always close connection
        session.close()
