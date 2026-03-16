"""
Pytest configuration and fixtures for testing.
"""
import pytest
from uuid import UUID
from typing import Optional

from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy import text
from sqlalchemy.pool import StaticPool, NullPool
from sqlalchemy.orm import sessionmaker
from app.core.database import SessionLocal
from app.core.config import settings

# Import all models to ensure SQLAlchemy relationships are configured
from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.memories_events import MemoryEvent
from app.models.database.user import User


# ---------------------------------------------------------------------------
# Test user for non-integration tests (same as integration tests)
# ---------------------------------------------------------------------------

TEST_USER_EMAIL = "test-integration-a@elephantasm.test"


def _get_admin_session() -> Session:
    """Superuser session via MIGRATION_DATABASE_URL (bypasses RLS)."""
    url = settings.MIGRATION_DATABASE_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, poolclass=NullPool)
    factory = sessionmaker(bind=engine, class_=Session)
    return factory()


def _find_test_user() -> Optional[dict]:
    """Look up test user + org via admin session."""
    session = _get_admin_session()
    try:
        result = session.execute(text("""
            SELECT u.id as user_id, o.id as org_id
            FROM users u
            JOIN organization_members om ON om.user_id = u.id
            JOIN organizations o ON o.id = om.organization_id
            WHERE u.is_deleted = false AND o.is_deleted = false
              AND u.email = :email
            LIMIT 1
        """), {"email": TEST_USER_EMAIL})
        row = result.fetchone()
        if row:
            return {
                "user_id": UUID(str(row.user_id)),
                "org_id": UUID(str(row.org_id)),
            }
        return None
    finally:
        session.close()


@pytest.fixture(name="db_session", scope="function")
def db_session_fixture():
    """
    Provides a clean database session for each test.

    Uses the existing database engine from app.core.database.
    Creates a new session for each test and rolls back after completion.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()  # Rollback to ensure test isolation
        session.close()


@pytest.fixture(scope="session")
def test_user_context() -> dict:
    """
    Shared test user context (user_id + org_id) for non-integration tests.

    Session-scoped: looked up once, reused across all tests.
    """
    ctx = _find_test_user()
    if ctx is None:
        pytest.skip(
            f"Test user '{TEST_USER_EMAIL}' not found. "
            "Create this user via the app before running these tests."
        )
    return ctx


@pytest.fixture(name="rls_session", scope="function")
def rls_session_fixture(test_user_context):
    """
    Database session with RLS context (app.current_user) pre-set.

    Use this instead of db_session when tests create entities via ORM
    (Anima, User, Memory, etc.) that are subject to RLS policies.
    Rolls back after each test for isolation.
    """
    session = SessionLocal()
    try:
        user_id = str(test_user_context["user_id"])
        # Use session-level (false) not transaction-local (true) so the
        # setting survives commit() calls within the test.
        session.execute(
            text("SELECT set_config('app.current_user', :uid, false)"),
            {"uid": user_id},
        )
        yield session
    finally:
        session.rollback()
        session.close()
