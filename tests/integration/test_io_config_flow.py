"""
Integration tests for IOConfig API.

Tests cover:
- Auto-creation with defaults on first GET
- Idempotent GET (returns existing config)
- Partial update via PATCH (deep merge)
- Read-only and write-only setting updates
- Nested JSONB preservation during partial updates
- Reset to defaults
- Defaults endpoint (no auth)
- 404 for non-existent anima
"""

import pytest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.models.database.io_config import DEFAULT_READ_SETTINGS, DEFAULT_WRITE_SETTINGS


class TestGetIOConfig:
    """Tests for GET /api/animas/{anima_id}/io-config."""

    def test_auto_creates_with_defaults(self, client: TestClient, test_anima: dict):
        """First GET auto-creates config with default settings."""
        response = client.get(f"/api/animas/{test_anima['id']}/io-config")

        assert response.status_code == 200
        data = response.json()
        assert data["anima_id"] == test_anima["id"]
        assert data["read_settings"] == DEFAULT_READ_SETTINGS
        assert data["write_settings"] == DEFAULT_WRITE_SETTINGS
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_idempotent_returns_existing(self, client: TestClient, test_anima: dict):
        """Second GET returns same config (no duplicate creation)."""
        first = client.get(f"/api/animas/{test_anima['id']}/io-config").json()
        second = client.get(f"/api/animas/{test_anima['id']}/io-config").json()

        assert first["id"] == second["id"]
        assert first["created_at"] == second["created_at"]

    def test_nonexistent_anima_rejected(self, client: TestClient):
        """GET for non-existent anima is rejected by RLS."""
        fake_id = str(uuid4())

        # get_or_create tries to INSERT → RLS blocks (anima not owned).
        # Route only catches ValueError, so SQLAlchemy ProgrammingError
        # propagates as unhandled exception (500 in production).
        with pytest.raises(Exception):
            client.get(f"/api/animas/{fake_id}/io-config")


class TestUpdateIOConfig:
    """Tests for PATCH /api/animas/{anima_id}/io-config."""

    def test_partial_update_deep_merges(self, client: TestClient, test_anima: dict):
        """PATCH deep-merges provided settings with existing."""
        # First, get defaults
        client.get(f"/api/animas/{test_anima['id']}/io-config")

        # Partial update — only change token_budget in write_settings
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config",
            json={"write_settings": {"token_budget": 8000}}
        )

        assert response.status_code == 200
        data = response.json()
        # Changed field
        assert data["write_settings"]["token_budget"] == 8000
        # Unchanged fields preserved
        assert data["write_settings"]["preset"] == "conversational"
        assert data["write_settings"]["weights"] == DEFAULT_WRITE_SETTINGS["weights"]
        assert data["write_settings"]["limits"] == DEFAULT_WRITE_SETTINGS["limits"]
        # Read settings untouched
        assert data["read_settings"] == DEFAULT_READ_SETTINGS

    def test_nested_jsonb_preserved(self, client: TestClient, test_anima: dict):
        """Deep merge preserves sibling keys in nested dicts."""
        # Update only one weight
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config",
            json={"write_settings": {"weights": {"importance": 0.50}}}
        )

        assert response.status_code == 200
        weights = response.json()["write_settings"]["weights"]
        # Updated key
        assert weights["importance"] == 0.50
        # Sibling keys preserved
        assert weights["confidence"] == DEFAULT_WRITE_SETTINGS["weights"]["confidence"]
        assert weights["recency"] == DEFAULT_WRITE_SETTINGS["weights"]["recency"]
        assert weights["decay"] == DEFAULT_WRITE_SETTINGS["weights"]["decay"]
        assert weights["similarity"] == DEFAULT_WRITE_SETTINGS["weights"]["similarity"]

    def test_update_both_settings(self, client: TestClient, test_anima: dict):
        """PATCH can update read and write settings simultaneously."""
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config",
            json={
                "read_settings": {"min_content_length": 10},
                "write_settings": {"similarity_threshold": 0.9}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["read_settings"]["min_content_length"] == 10
        assert data["write_settings"]["similarity_threshold"] == 0.9

    def test_update_nonexistent_anima_404(self, client: TestClient):
        """PATCH for non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.patch(
            f"/api/animas/{fake_id}/io-config",
            json={"write_settings": {"token_budget": 8000}}
        )

        assert response.status_code == 404


class TestUpdateReadSettings:
    """Tests for PATCH /api/animas/{anima_id}/io-config/read."""

    def test_update_read_settings_only(self, client: TestClient, test_anima: dict):
        """PATCH /read merges into read_settings, leaves write_settings alone."""
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config/read",
            json={"session_timeout_minutes": 60, "dedupe_window_minutes": 10}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["read_settings"]["session_timeout_minutes"] == 60
        assert data["read_settings"]["dedupe_window_minutes"] == 10
        # Other read keys preserved
        assert data["read_settings"]["event_types"] == DEFAULT_READ_SETTINGS["event_types"]
        # Write untouched
        assert data["write_settings"] == DEFAULT_WRITE_SETTINGS

    def test_update_read_nested_source_filters(self, client: TestClient, test_anima: dict):
        """Nested source_filters dict is deep-merged."""
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config/read",
            json={"source_filters": {"include": ["sdk"]}}
        )

        assert response.status_code == 200
        filters = response.json()["read_settings"]["source_filters"]
        assert filters["include"] == ["sdk"]
        # Lists are replaced, not merged — exclude stays as default
        assert filters["exclude"] == []


class TestUpdateWriteSettings:
    """Tests for PATCH /api/animas/{anima_id}/io-config/write."""

    def test_update_write_settings_only(self, client: TestClient, test_anima: dict):
        """PATCH /write merges into write_settings, leaves read_settings alone."""
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config/write",
            json={"preset": "analytical", "token_budget": 6000}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["write_settings"]["preset"] == "analytical"
        assert data["write_settings"]["token_budget"] == 6000
        # Other write keys preserved
        assert data["write_settings"]["include_identity"] is True
        # Read untouched
        assert data["read_settings"] == DEFAULT_READ_SETTINGS

    def test_update_write_injection_nested(self, client: TestClient, test_anima: dict):
        """Nested injection dict is deep-merged."""
        response = client.patch(
            f"/api/animas/{test_anima['id']}/io-config/write",
            json={"injection": {"cooldown_seconds": 30}}
        )

        assert response.status_code == 200
        injection = response.json()["write_settings"]["injection"]
        assert injection["cooldown_seconds"] == 30
        # Sibling keys preserved
        assert injection["trigger"] == "every_turn"
        assert injection["drift_detection"] is False


class TestResetIOConfig:
    """Tests for POST /api/animas/{anima_id}/io-config/reset."""

    def test_reset_restores_defaults(self, client: TestClient, test_anima: dict):
        """Reset overwrites all custom settings with defaults."""
        # First, customize settings
        client.patch(
            f"/api/animas/{test_anima['id']}/io-config",
            json={
                "read_settings": {"min_content_length": 100},
                "write_settings": {"token_budget": 16000, "preset": "analytical"}
            }
        )

        # Verify customization took effect
        customized = client.get(f"/api/animas/{test_anima['id']}/io-config").json()
        assert customized["read_settings"]["min_content_length"] == 100
        assert customized["write_settings"]["token_budget"] == 16000

        # Reset
        response = client.post(f"/api/animas/{test_anima['id']}/io-config/reset")

        assert response.status_code == 200
        data = response.json()
        assert data["read_settings"] == DEFAULT_READ_SETTINGS
        assert data["write_settings"] == DEFAULT_WRITE_SETTINGS

    def test_reset_nonexistent_anima_404(self, client: TestClient):
        """Reset for non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.post(f"/api/animas/{fake_id}/io-config/reset")

        assert response.status_code == 404


class TestGetDefaults:
    """Tests for GET /api/io-config/defaults."""

    def test_returns_default_settings(self, client: TestClient):
        """Defaults endpoint returns both read and write defaults."""
        response = client.get("/api/io-config/defaults")

        assert response.status_code == 200
        data = response.json()
        assert data["read_settings"] == DEFAULT_READ_SETTINGS
        assert data["write_settings"] == DEFAULT_WRITE_SETTINGS

    def test_defaults_no_auth_required(self, unauthenticated_client: TestClient):
        """Defaults endpoint works without authentication."""
        response = unauthenticated_client.get("/api/io-config/defaults")

        assert response.status_code == 200
        data = response.json()
        assert "read_settings" in data
        assert "write_settings" in data
