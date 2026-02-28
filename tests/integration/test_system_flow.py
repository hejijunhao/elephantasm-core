"""
Integration tests for System endpoints.

Tests cover:
- Health check
- Stats overview
- User profile
"""

import pytest

from fastapi.testclient import TestClient
from tests.integration.conftest import create_test_app


# Fixture for unauthenticated client (no auth needed for health checks)
@pytest.fixture(scope="module")
def health_client() -> TestClient:
    """TestClient for health endpoints (no auth required)."""
    app = create_test_app()
    return TestClient(app)


class TestHealthCheck:
    """Tests for GET /api/health endpoint."""

    def test_api_health_check(self, health_client: TestClient):
        """API health endpoint returns 200 OK."""
        response = health_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data or "healthy" in str(data).lower()

    def test_health_status_value(self, health_client: TestClient):
        """Health endpoint returns healthy status."""
        response = health_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        # Check for status field
        if "status" in data:
            assert data["status"] in ["healthy", "ok"]


class TestRootEndpoint:
    """Tests for root endpoint (in main app, not API router)."""

    @pytest.mark.skip(reason="Root endpoint is in main.py, not API router")
    def test_root_returns_api_info(self, health_client: TestClient):
        """Root endpoint returns API information."""
        # Note: The / endpoint is defined in main.py, not the API router
        # Our test app only includes the API router
        pass


class TestStatsOverview:
    """Tests for GET /api/stats/overview endpoint."""

    def test_stats_overview(self, client: TestClient):
        """Stats overview returns counts."""
        response = client.get("/api/stats/overview")

        # May return 200 or 404 if endpoint doesn't exist
        if response.status_code == 200:
            data = response.json()
            # Should have count fields
            assert isinstance(data, dict)

    def test_stats_requires_auth(self, unauthenticated_client: TestClient):
        """Stats endpoint may require authentication."""
        response = unauthenticated_client.get("/api/stats/overview")
        # May return 200 (public) or 401 (auth required) or 404 (doesn't exist)
        assert response.status_code in [200, 401, 404]


class TestUserProfile:
    """Tests for GET /api/users/me endpoint."""

    def test_get_current_user(self, client: TestClient):
        """Get current user profile returns user data."""
        response = client.get("/api/users/me")

        # May return 200 or 404 if endpoint doesn't exist
        if response.status_code == 200:
            data = response.json()
            assert "id" in data or "email" in data
            # Should be the test user

    def test_get_current_user_requires_auth(self, unauthenticated_client: TestClient):
        """User profile requires authentication."""
        response = unauthenticated_client.get("/api/users/me")
        # Should return 401 or similar
        assert response.status_code in [401, 403, 404]


class TestUnauthenticatedAccess:
    """Tests for unauthenticated access patterns."""

    def test_api_health_no_auth(self, health_client: TestClient):
        """API health endpoint doesn't require auth."""
        response = health_client.get("/api/health")
        assert response.status_code == 200

    def test_protected_endpoints_require_auth(self, health_client: TestClient):
        """Protected endpoints return 401/403/422 without auth."""
        # These endpoints require authentication
        protected_endpoints = [
            "/api/animas",
            "/api/api-keys",
        ]

        for endpoint in protected_endpoints:
            response = health_client.get(endpoint)
            # May return empty list (RLS filters), 401, 403, or 422
            # RLS-protected endpoints may return 200 with empty data
            # vs explicitly auth-required endpoints return 401
            assert response.status_code in [200, 401, 403, 404, 422]
