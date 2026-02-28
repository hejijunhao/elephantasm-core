"""
Integration test fixtures for FastAPI TestClient.

Provides:
- TestClient with auth override (no JWKS/API key validation)
- Designated test user context (test-integration-a@elephantasm.test)
- RLS context injection for multi-tenant isolation
- Auto-cleanup of test data after test session

Strategy:
- Uses MIGRATION_DATABASE_URL (postgres superuser) for test fixture queries
- Tests run exclusively under designated test user account
- All test data deleted after test session completes
"""

import pytest
from typing import Generator, Optional
from uuid import UUID, uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from fastapi.responses import JSONResponse

from app.core.database import SessionLocal
from app.core.auth import get_current_user_id, require_current_user_id
from app.core.rls_dependencies import get_db_with_rls
from app.api.router import api_router
from app.core.config import settings
from app.domain.exceptions import (
    EntityNotFoundError,
    EntityDeletedError,
    DuplicateEntityError,
    DomainValidationError,
)


# ---------------------------------------------------------------------------
# Test User Configuration
# ---------------------------------------------------------------------------

TEST_USER_EMAIL = "test-integration-a@elephantasm.test"


# ---------------------------------------------------------------------------
# Admin Session (uses MIGRATION_DATABASE_URL - bypasses RLS)
# ---------------------------------------------------------------------------

def get_admin_session() -> Session:
    """
    Get a database session using MIGRATION_DATABASE_URL (postgres superuser).

    This bypasses RLS and is used only for test fixture setup/queries.
    """
    migration_url = settings.MIGRATION_DATABASE_URL
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = create_engine(migration_url, poolclass=NullPool)
    session_factory = sessionmaker(bind=engine, class_=Session)
    return session_factory()


# ---------------------------------------------------------------------------
# App Factory (no lifespan - skips schedulers)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def test_lifespan(app: FastAPI):
    """Minimal lifespan that skips scheduler registration."""
    yield


def create_test_app() -> FastAPI:
    """Create FastAPI app for testing without scheduler overhead.

    Registers domain exception handlers to match production behavior (main.py).
    """
    app = FastAPI(
        title="Elephantasm Test API",
        lifespan=test_lifespan,
    )

    # Domain exception → HTTP response mapping (mirrors main.py)
    @app.exception_handler(EntityNotFoundError)
    async def _not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EntityDeletedError)
    async def _deleted(request, exc):
        return JSONResponse(status_code=410, content={"detail": str(exc)})

    @app.exception_handler(DuplicateEntityError)
    async def _duplicate(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(DomainValidationError)
    async def _validation(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(api_router, prefix=settings.API_PREFIX)
    return app


# ---------------------------------------------------------------------------
# Database Session Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Fresh database session per test with rollback."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# Find Existing Test User (works with RLS-enabled database)
# ---------------------------------------------------------------------------

def find_test_user_context(session: Session) -> Optional[dict]:
    """
    Find the designated test user by email.

    Queries users table to find the test user that has:
    - Organization membership
    - Active subscription
    - Usage counter

    Returns dict with user_id, org_id, or None if not found.
    """
    result = session.execute(text("""
        SELECT
            u.id as user_id,
            u.auth_uid,
            u.email,
            o.id as org_id
        FROM users u
        JOIN organization_members om ON om.user_id = u.id
        JOIN organizations o ON o.id = om.organization_id
        JOIN subscriptions s ON s.organization_id = o.id
        JOIN usage_counters uc ON uc.organization_id = o.id
        WHERE u.is_deleted = false
          AND o.is_deleted = false
          AND u.email = :email
        LIMIT 1
    """), {"email": TEST_USER_EMAIL})

    row = result.fetchone()
    if row:
        return {
            "user_id": UUID(str(row.user_id)),
            "auth_uid": UUID(str(row.auth_uid)),
            "email": row.email,
            "org_id": UUID(str(row.org_id)),
        }
    return None


# ---------------------------------------------------------------------------
# Test Context Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_context() -> dict:
    """
    Get test context for the designated test user.

    Uses admin session (postgres superuser) to bypass RLS.
    Skips tests if test user not found.
    """
    session = get_admin_session()
    try:
        context = find_test_user_context(session)
        if context is None:
            pytest.skip(
                f"Test user '{TEST_USER_EMAIL}' not found. "
                "Create this user via the app before running integration tests."
            )
        return context
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def reset_test_state_before_tests(test_context: dict):
    """
    Clean up stale test data and reset usage counter before test session.

    Non-integration tests (domain/workflow/services) create animas via
    rls_session with explicit commit() — these survive the fixture's
    rollback() and accumulate across runs. This fixture purges them
    and recounts the usage counter so RequireActionAllowed doesn't 403.
    """
    session = get_admin_session()
    user_id = str(test_context["user_id"])
    org_id = str(test_context["org_id"])
    try:
        # Delete orphaned test animas (left by non-integration tests)
        # FK-safe order: children before parent
        session.execute(text("""
            DELETE FROM dream_actions WHERE session_id IN (
                SELECT id FROM dream_sessions
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :uid))
        """), {"uid": user_id})
        session.execute(text("""
            DELETE FROM identity_audit_log WHERE identity_id IN (
                SELECT id FROM identities
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :uid))
        """), {"uid": user_id})
        session.execute(text("""
            DELETE FROM knowledge_audit_log WHERE knowledge_id IN (
                SELECT id FROM knowledge
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :uid))
        """), {"uid": user_id})
        session.execute(text("""
            DELETE FROM memories_events WHERE memory_id IN (
                SELECT id FROM memories
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :uid))
        """), {"uid": user_id})
        for table in [
            "dream_sessions", "memory_packs", "io_configs",
            "synthesis_configs", "identities", "knowledge",
            "memories", "events",
        ]:
            session.execute(text(
                f"DELETE FROM {table} WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :uid)"
            ), {"uid": user_id})
        session.execute(text("DELETE FROM api_keys WHERE user_id = :uid"), {"uid": user_id})
        session.execute(text("DELETE FROM animas WHERE user_id = :uid"), {"uid": user_id})

        # Reset usage counter to match actual DB state (now 0)
        session.execute(text("""
            UPDATE usage_counters
            SET active_anima_count = 0, dormant_anima_count = 0
            WHERE organization_id = :oid
        """), {"oid": org_id})

        session.commit()
        print(f"\n[SETUP] Stale test data purged + counter reset for org {org_id}")
    except Exception as e:
        session.rollback()
        print(f"\n[SETUP ERROR] {e}")
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data(test_context: dict):
    """
    Delete all test-created data after test session completes.

    Runs automatically after all tests finish.
    Uses FK-safe deletion order (children before parents).
    """
    yield  # Run all tests first

    session = get_admin_session()
    user_id = test_context["user_id"]

    # Multi-hop deletes: tables without direct anima_id FK
    # dream_actions → dream_sessions.anima_id
    # identity_audit_log → identities.anima_id
    # knowledge_audit_log → knowledge.anima_id
    # memories_events → memories.anima_id
    try:
        session.execute(text("""
            DELETE FROM dream_actions
            WHERE session_id IN (
                SELECT id FROM dream_sessions
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :user_id)
            )
        """), {"user_id": str(user_id)})

        session.execute(text("""
            DELETE FROM identity_audit_log
            WHERE identity_id IN (
                SELECT id FROM identities
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :user_id)
            )
        """), {"user_id": str(user_id)})

        session.execute(text("""
            DELETE FROM knowledge_audit_log
            WHERE knowledge_id IN (
                SELECT id FROM knowledge
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :user_id)
            )
        """), {"user_id": str(user_id)})

        session.execute(text("""
            DELETE FROM memories_events
            WHERE memory_id IN (
                SELECT id FROM memories
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :user_id)
            )
        """), {"user_id": str(user_id)})

        # Tables with direct anima_id FK
        tables_with_anima_fk = [
            "dream_sessions",
            "memory_packs",
            "io_configs",
            "synthesis_configs",
            "identities",
            "knowledge",
            "memories",
            "events",
        ]

        for table in tables_with_anima_fk:
            session.execute(text(f"""
                DELETE FROM {table}
                WHERE anima_id IN (SELECT id FROM animas WHERE user_id = :user_id)
            """), {"user_id": str(user_id)})

        # Delete API keys for user
        session.execute(text(
            "DELETE FROM api_keys WHERE user_id = :user_id"
        ), {"user_id": str(user_id)})

        # Finally delete animas
        session.execute(text(
            "DELETE FROM animas WHERE user_id = :user_id"
        ), {"user_id": str(user_id)})

        # Reset usage counter — all animas deleted, counts are genuinely 0
        session.execute(text("""
            UPDATE usage_counters
            SET active_anima_count = 0, dormant_anima_count = 0
            WHERE organization_id = :org_id
        """), {"org_id": str(test_context["org_id"])})

        session.commit()
        print(f"\n[CLEANUP] Test data deleted for {test_context['email']}")
    except Exception as e:
        session.rollback()
        print(f"\n[CLEANUP ERROR] {e}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Per-Test Anima Fixture (function-scoped with teardown)
# ---------------------------------------------------------------------------

def _cleanup_anima(anima_id: str, org_id: str = None):
    """FK-safe delete of a single anima and all child records.

    If org_id is provided, refreshes usage_counters.active_anima_count
    after deletion to prevent counter drift across test runs.
    """
    session = get_admin_session()
    try:
        aid = {"aid": anima_id}

        # Multi-hop: tables without direct anima_id FK
        session.execute(text("""
            DELETE FROM dream_actions
            WHERE session_id IN (
                SELECT id FROM dream_sessions WHERE anima_id = :aid
            )
        """), aid)
        session.execute(text("""
            DELETE FROM identity_audit_log
            WHERE identity_id IN (
                SELECT id FROM identities WHERE anima_id = :aid
            )
        """), aid)
        session.execute(text("""
            DELETE FROM knowledge_audit_log
            WHERE knowledge_id IN (
                SELECT id FROM knowledge WHERE anima_id = :aid
            )
        """), aid)
        session.execute(text("""
            DELETE FROM memories_events
            WHERE memory_id IN (
                SELECT id FROM memories WHERE anima_id = :aid
            )
        """), aid)

        # Direct anima_id FK tables
        for table in [
            "dream_sessions", "memory_packs", "io_configs",
            "synthesis_configs", "identities", "knowledge",
            "memories", "events",
        ]:
            session.execute(text(
                f"DELETE FROM {table} WHERE anima_id = :aid"
            ), aid)

        # Finally the anima itself
        session.execute(text("DELETE FROM animas WHERE id = :aid"), aid)

        # Refresh usage counter to match actual DB state
        if org_id:
            session.execute(text("""
                UPDATE usage_counters
                SET active_anima_count = (
                    SELECT COUNT(*) FROM animas a
                    JOIN users u ON u.id = a.user_id
                    JOIN organization_members om ON om.user_id = u.id
                    WHERE om.organization_id = :oid
                      AND a.is_deleted = false AND a.is_dormant = false
                ),
                dormant_anima_count = (
                    SELECT COUNT(*) FROM animas a
                    JOIN users u ON u.id = a.user_id
                    JOIN organization_members om ON om.user_id = u.id
                    WHERE om.organization_id = :oid
                      AND a.is_deleted = false AND a.is_dormant = true
                )
                WHERE organization_id = :oid
            """), {"oid": org_id})

        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[CLEANUP ERROR] anima {anima_id}: {e}")
    finally:
        session.close()


@pytest.fixture(scope="function")
def test_anima(client: TestClient, test_context: dict) -> Generator[dict, None, None]:
    """
    Create a test anima, yield it, then cascade-delete all its data.

    Function-scoped: each test gets a fresh anima that is fully cleaned
    up in teardown, even if the test fails or the session is interrupted.
    Passes org_id so _cleanup_anima refreshes the usage counter.
    """
    response = client.post(
        "/api/animas",
        json={"name": f"_test_{uuid4().hex[:8]}"}
    )
    assert response.status_code == 201
    anima = response.json()

    yield anima

    _cleanup_anima(anima["id"], org_id=str(test_context["org_id"]))


# ---------------------------------------------------------------------------
# Auth Override Factory
# ---------------------------------------------------------------------------

def make_auth_override(user_id: UUID):
    """Create auth dependency override that returns given user_id."""
    async def override_get_current_user_id():
        return user_id

    async def override_require_current_user_id():
        return user_id

    return override_get_current_user_id, override_require_current_user_id


def make_db_with_rls_override(user_id: UUID):
    """Create database dependency override with RLS context."""
    async def override_get_db_with_rls() -> Generator[Session, None, None]:
        session = SessionLocal()
        try:
            # Set RLS context
            if user_id is not None:
                user_id_str = str(user_id)
                session.execute(text(f"SET LOCAL \"app.current_user\" = '{user_id_str}'"))
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return override_get_db_with_rls


# ---------------------------------------------------------------------------
# TestClient Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(test_context: dict) -> Generator[TestClient, None, None]:
    """
    TestClient with auth overrides for test_user.

    All requests are authenticated as test_user with RLS context.
    """
    app = create_test_app()
    user_id = test_context["user_id"]

    # Create overrides
    auth_override, require_auth_override = make_auth_override(user_id)
    db_rls_override = make_db_with_rls_override(user_id)

    # Apply overrides
    app.dependency_overrides[get_current_user_id] = auth_override
    app.dependency_overrides[require_current_user_id] = require_auth_override
    app.dependency_overrides[get_db_with_rls] = db_rls_override

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def unauthenticated_client() -> Generator[TestClient, None, None]:
    """TestClient without auth (returns None for user_id)."""
    app = create_test_app()

    async def no_auth():
        return None

    app.dependency_overrides[get_current_user_id] = no_auth

    with TestClient(app) as c:
        yield c
