"""
Integration test for real API key authentication (no auth mocking).

Tests the actual _validate_api_key -> SECURITY DEFINER bypass -> bcrypt path.
This is the path that was broken due to RLS chicken-and-egg (08P).

Unlike other integration tests that override auth dependencies, these tests
exercise the full auth chain against the real database with ZERO overrides.
"""

import pytest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.integration.conftest import (
    create_test_app,
    get_admin_session,
)
from app.domain.api_key_operations import APIKeyOperations
from app.models.database.api_key import APIKeyCreate


@pytest.fixture
def api_key_for_test(test_context: dict):
    """
    Create a real API key via admin session (bypasses RLS).

    Yields (full_key, api_key_id) then cleans up.
    """
    session = get_admin_session()
    try:
        api_key_obj, full_key = APIKeyOperations.create(
            session,
            test_context["user_id"],
            APIKeyCreate(name="integration-test-08P"),
        )
        session.commit()
        key_id = api_key_obj.id
    finally:
        session.close()

    yield full_key, key_id

    # Cleanup
    session = get_admin_session()
    try:
        session.execute(
            text("DELETE FROM api_keys WHERE id = :id"),
            {"id": str(key_id)},
        )
        session.commit()
    finally:
        session.close()


def _make_real_auth_client() -> TestClient:
    """
    Create TestClient with ZERO dependency overrides.

    The full auth chain runs: Authorization header -> _validate_api_key()
    -> SECURITY DEFINER lookup -> bcrypt -> user_id -> get_db_with_rls.
    """
    app = create_test_app()
    return TestClient(app)


class TestRealAPIKeyAuth:
    """Tests that exercise the real API key auth chain (no mocks)."""

    def test_valid_api_key_authenticates(self, test_context, api_key_for_test):
        """Real API key should authenticate and return 200."""
        full_key, _ = api_key_for_test

        with _make_real_auth_client() as client:
            response = client.get(
                "/api/animas",
                headers={"Authorization": f"Bearer {full_key}"},
            )

        assert response.status_code == 200

    def test_invalid_api_key_returns_401(self):
        """Bogus sk_live_ key should return 401."""
        with _make_real_auth_client() as client:
            response = client.get(
                "/api/animas",
                headers={
                    "Authorization": "Bearer sk_fake_0000000000000000000000000000000000000000"
                },
            )

        assert response.status_code == 401

    def test_missing_auth_header_returns_401(self):
        """No Authorization header should return 401."""
        with _make_real_auth_client() as client:
            response = client.get("/api/animas")

        assert response.status_code == 401

    def test_api_key_updates_usage_stats(self, test_context, api_key_for_test):
        """Successful auth should increment request_count and set last_used_at."""
        full_key, key_id = api_key_for_test

        with _make_real_auth_client() as client:
            response = client.get(
                "/api/animas",
                headers={"Authorization": f"Bearer {full_key}"},
            )

        assert response.status_code == 200

        # Verify usage stats via admin session
        session = get_admin_session()
        try:
            result = session.execute(
                text("SELECT request_count, last_used_at FROM api_keys WHERE id = :id"),
                {"id": str(key_id)},
            )
            row = result.fetchone()
            assert row is not None
            assert row.request_count >= 1
            assert row.last_used_at is not None
        finally:
            session.close()
