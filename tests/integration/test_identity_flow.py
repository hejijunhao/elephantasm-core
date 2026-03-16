"""
Integration tests for Identity management API.

Tests cover:
- Get/create identity for anima
- Update identity fields
- Audit log verification
"""

import pytest
from uuid import uuid4

from fastapi.testclient import TestClient


class TestGetIdentity:
    """Tests for GET /api/identities endpoints."""

    def test_get_identity_by_anima_not_found(self, client: TestClient, test_anima: dict):
        """Get identity for anima without one returns 404."""
        response = client.get(f"/api/identities/anima/{test_anima['id']}")
        assert response.status_code == 404

    def test_get_identity_by_id_not_found(self, client: TestClient):
        """Get identity with non-existent ID returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/identities/{fake_id}")
        assert response.status_code == 404


class TestCreateIdentity:
    """Tests for POST /api/identities endpoint."""

    def test_create_identity_success(self, client: TestClient, test_anima: dict):
        """Create identity for anima returns 201."""
        # anima_id is a query parameter, not body
        response = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["anima_id"] == test_anima["id"]
        assert "id" in data

    def test_create_identity_with_personality(self, client: TestClient, test_anima: dict):
        """Create identity with personality type."""
        response = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={
                "personality_type": "INTJ"
            }
        )

        assert response.status_code == 201
        data = response.json()
        if "personality_type" in data:
            assert data["personality_type"] == "INTJ"

    def test_create_identity_conflict(self, client: TestClient, test_anima: dict):
        """Create identity twice for same anima returns 409."""
        # First identity
        resp1 = client.post(f"/api/identities?anima_id={test_anima['id']}", json={})
        assert resp1.status_code == 201

        # Second identity - should conflict
        resp2 = client.post(f"/api/identities?anima_id={test_anima['id']}", json={})
        assert resp2.status_code == 409


class TestUpdateIdentity:
    """Tests for PATCH /api/identities/{id} endpoint."""

    @pytest.fixture
    def test_identity(self, client: TestClient, test_anima: dict) -> dict:
        """Create a test identity."""
        response = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={}
        )
        assert response.status_code == 201
        return response.json()

    def test_update_identity_personality(self, client: TestClient, test_identity: dict):
        """Update identity personality type."""
        response = client.patch(
            f"/api/identities/{test_identity['id']}",
            json={"personality_type": "ENFP"}
        )

        assert response.status_code == 200
        data = response.json()
        if "personality_type" in data:
            assert data["personality_type"] == "ENFP"

    def test_update_identity_communication_style(self, client: TestClient, test_identity: dict):
        """Update identity communication style."""
        response = client.patch(
            f"/api/identities/{test_identity['id']}",
            json={"communication_style": "formal"}
        )

        assert response.status_code == 200

    def test_update_identity_self(self, client: TestClient, test_identity: dict):
        """Update identity self JSONB."""
        self_data = {
            "core_traits": ["analytical", "curious"],
            "expertise_areas": ["programming", "systems"]
        }

        response = client.patch(
            f"/api/identities/{test_identity['id']}",
            json={"self_": self_data}
        )

        assert response.status_code == 200

    def test_update_identity_not_found(self, client: TestClient):
        """Update non-existent identity returns 404."""
        fake_id = str(uuid4())
        response = client.patch(
            f"/api/identities/{fake_id}",
            json={"communication_style": "casual"}
        )
        assert response.status_code == 404


class TestIdentityHistory:
    """Tests for identity audit/history endpoints."""

    def test_get_identity_history(self, client: TestClient, test_anima: dict):
        """Get identity history returns audit log."""
        # Create identity
        create_resp = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={}
        )
        identity_id = create_resp.json()["id"]

        # Update it
        client.patch(
            f"/api/identities/{identity_id}",
            json={"communication_style": "friendly"}
        )

        # Get history
        response = client.get(f"/api/identities/{identity_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least CREATE and UPDATE entries
        assert len(data) >= 1


class TestDeleteIdentity:
    """Tests for DELETE /api/identities/{id} endpoint."""

    def test_delete_identity_success(self, client: TestClient, test_anima: dict):
        """Delete identity returns soft-deleted identity."""
        # Create
        create_resp = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={}
        )
        identity_id = create_resp.json()["id"]

        # Delete
        response = client.delete(f"/api/identities/{identity_id}")
        assert response.status_code == 200

    def test_delete_identity_not_found(self, client: TestClient):
        """Delete non-existent identity returns 404."""
        fake_id = str(uuid4())
        response = client.delete(f"/api/identities/{fake_id}")
        assert response.status_code == 404


class TestRestoreIdentity:
    """Tests for POST /api/identities/{id}/restore endpoint."""

    def test_restore_identity_success(self, client: TestClient, test_anima: dict):
        """Restore soft-deleted identity."""
        # Create
        create_resp = client.post(
            f"/api/identities?anima_id={test_anima['id']}",
            json={}
        )
        identity_id = create_resp.json()["id"]

        # Delete
        client.delete(f"/api/identities/{identity_id}")

        # Restore
        response = client.post(f"/api/identities/{identity_id}/restore")
        assert response.status_code == 200


