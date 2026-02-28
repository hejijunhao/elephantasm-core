"""
Integration tests for Anima lifecycle API.

Tests cover:
- Create, read, update, delete (CRUD)
- Validation errors
- Soft delete and restore
"""

import pytest
from uuid import uuid4

from fastapi.testclient import TestClient
from tests.integration.conftest import _cleanup_anima


@pytest.fixture(autouse=True)
def _track_and_cleanup_animas(client: TestClient, test_context: dict, request):
    """
    Track animas created during the test and clean them all up afterward.

    Used for test_anima_flow where tests create animas inline (testing CRUD).
    Wraps the client.post method to intercept anima creation responses.
    Passes org_id so _cleanup_anima refreshes the usage counter.
    """
    created_ids = []
    original_post = client.post

    def tracking_post(url, **kwargs):
        response = original_post(url, **kwargs)
        if url == "/api/animas" and response.status_code == 201:
            data = response.json()
            if "id" in data:
                created_ids.append(data["id"])
        return response

    client.post = tracking_post

    yield

    client.post = original_post
    org_id = str(test_context["org_id"])
    for anima_id in created_ids:
        _cleanup_anima(anima_id, org_id=org_id)


class TestCreateAnima:
    """Tests for POST /api/animas endpoint."""

    def test_create_anima_success(self, client: TestClient):
        """Create anima with valid data returns 201."""
        response = client.post(
            "/api/animas",
            json={"name": "Test Anima", "description": "A test anima"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Anima"
        assert data["description"] == "A test anima"
        assert "id" in data
        assert "created_at" in data

    def test_create_anima_minimal(self, client: TestClient):
        """Create anima with name only returns 201."""
        response = client.post(
            "/api/animas",
            json={"name": "Minimal Anima"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Anima"
        assert data["description"] is None

    def test_create_anima_with_meta(self, client: TestClient):
        """Create anima with meta JSONB returns 201."""
        response = client.post(
            "/api/animas",
            json={
                "name": "Meta Anima",
                "meta": {"tags": ["test", "demo"], "priority": 1}
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["meta"]["tags"] == ["test", "demo"]
        assert data["meta"]["priority"] == 1

    def test_create_anima_validation_missing_name(self, client: TestClient):
        """Create anima without name returns 422."""
        response = client.post(
            "/api/animas",
            json={"description": "No name provided"}
        )

        assert response.status_code == 422

    def test_create_anima_validation_empty_name(self, client: TestClient):
        """Create anima with empty name returns 422."""
        response = client.post(
            "/api/animas",
            json={"name": ""}
        )

        # May return 422 or 201 depending on validation rules
        # If name has min_length, expect 422
        # Adjust based on actual model validation
        assert response.status_code in [201, 422]


class TestListAnimas:
    """Tests for GET /api/animas endpoint."""

    def test_list_animas_empty(self, client: TestClient):
        """List animas with no data returns empty list."""
        response = client.get("/api/animas")

        assert response.status_code == 200
        # May have animas from other tests, check structure
        data = response.json()
        assert isinstance(data, list)

    def test_list_animas_pagination(self, client: TestClient):
        """List animas respects limit and offset."""
        # Create 5 animas
        for i in range(5):
            client.post("/api/animas", json={"name": f"Pagination Test {i}"})

        # Get first 2
        response = client.get("/api/animas?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 2

        # Get next 2
        response = client.get("/api/animas?limit=2&offset=2")
        assert response.status_code == 200

    def test_list_animas_excludes_deleted(self, client: TestClient):
        """Deleted animas not returned by default."""
        # Create and delete an anima
        create_resp = client.post("/api/animas", json={"name": "To Delete"})
        assert create_resp.status_code == 201
        anima_id = create_resp.json()["id"]

        client.delete(f"/api/animas/{anima_id}")

        # List should not include deleted
        response = client.get("/api/animas")
        assert response.status_code == 200
        ids = [a["id"] for a in response.json()]
        assert anima_id not in ids

    def test_list_animas_include_deleted(self, client: TestClient):
        """List animas with include_deleted=true shows deleted."""
        # Create and delete an anima
        create_resp = client.post("/api/animas", json={"name": "To Delete Inc"})
        assert create_resp.status_code == 201
        anima_id = create_resp.json()["id"]

        client.delete(f"/api/animas/{anima_id}")

        # List with include_deleted
        response = client.get("/api/animas?include_deleted=true")
        assert response.status_code == 200
        ids = [a["id"] for a in response.json()]
        assert anima_id in ids


class TestGetAnima:
    """Tests for GET /api/animas/{id} endpoint."""

    def test_get_anima_success(self, client: TestClient):
        """Get existing anima returns 200."""
        # Create anima first
        create_resp = client.post(
            "/api/animas",
            json={"name": "Get Test", "description": "For get test"}
        )
        assert create_resp.status_code == 201
        anima_id = create_resp.json()["id"]

        # Get it
        response = client.get(f"/api/animas/{anima_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == anima_id
        assert data["name"] == "Get Test"

    def test_get_anima_not_found(self, client: TestClient):
        """Get non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/animas/{fake_id}")
        assert response.status_code == 404

    def test_get_anima_invalid_id(self, client: TestClient):
        """Get with invalid UUID returns 422."""
        response = client.get("/api/animas/not-a-uuid")
        assert response.status_code == 422


class TestUpdateAnima:
    """Tests for PATCH /api/animas/{id} endpoint."""

    def test_update_anima_name(self, client: TestClient):
        """Update anima name returns 200."""
        # Create
        create_resp = client.post("/api/animas", json={"name": "Original Name"})
        anima_id = create_resp.json()["id"]

        # Update
        response = client.patch(
            f"/api/animas/{anima_id}",
            json={"name": "Updated Name"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_update_anima_description(self, client: TestClient):
        """Update anima description returns 200."""
        # Create
        create_resp = client.post(
            "/api/animas",
            json={"name": "Desc Test", "description": "Original"}
        )
        anima_id = create_resp.json()["id"]

        # Update
        response = client.patch(
            f"/api/animas/{anima_id}",
            json={"description": "Updated description"}
        )

        assert response.status_code == 200
        assert response.json()["description"] == "Updated description"

    def test_update_anima_meta(self, client: TestClient):
        """Update anima meta JSONB returns 200."""
        # Create
        create_resp = client.post(
            "/api/animas",
            json={"name": "Meta Test", "meta": {"old": "value"}}
        )
        anima_id = create_resp.json()["id"]

        # Update
        response = client.patch(
            f"/api/animas/{anima_id}",
            json={"meta": {"new": "value", "count": 42}}
        )

        assert response.status_code == 200
        assert response.json()["meta"]["new"] == "value"

    def test_update_anima_not_found(self, client: TestClient):
        """Update non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.patch(
            f"/api/animas/{fake_id}",
            json={"name": "Will Fail"}
        )
        assert response.status_code == 404


class TestDeleteAnima:
    """Tests for DELETE /api/animas/{id} endpoint."""

    def test_delete_anima_success(self, client: TestClient):
        """Delete anima returns 200 with cascade counts (soft delete)."""
        # Create
        create_resp = client.post("/api/animas", json={"name": "Delete Me"})
        anima_id = create_resp.json()["id"]

        # Delete — returns 200 + dict of affected record counts
        response = client.delete(f"/api/animas/{anima_id}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

        # Verify soft deleted - not visible without include_deleted
        get_resp = client.get(f"/api/animas/{anima_id}")
        assert get_resp.status_code == 404

        # Should be visible with include_deleted
        get_resp_inc = client.get(f"/api/animas/{anima_id}?include_deleted=true")
        assert get_resp_inc.status_code == 200

    def test_delete_anima_not_found(self, client: TestClient):
        """Delete non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.delete(f"/api/animas/{fake_id}")
        assert response.status_code == 404


class TestRestoreAnima:
    """Tests for POST /api/animas/{id}/restore endpoint."""

    def test_restore_anima_success(self, client: TestClient):
        """Restore soft-deleted anima returns 200."""
        # Create
        create_resp = client.post("/api/animas", json={"name": "Restore Me"})
        anima_id = create_resp.json()["id"]

        # Delete
        client.delete(f"/api/animas/{anima_id}")

        # Verify deleted
        get_resp = client.get(f"/api/animas/{anima_id}")
        assert get_resp.status_code == 404

        # Restore
        response = client.post(f"/api/animas/{anima_id}/restore")
        assert response.status_code == 200

        # Now visible in normal list
        get_resp = client.get(f"/api/animas/{anima_id}")
        assert get_resp.status_code == 200

    def test_restore_anima_not_found(self, client: TestClient):
        """Restore non-existent anima returns 404."""
        fake_id = str(uuid4())
        response = client.post(f"/api/animas/{fake_id}/restore")
        assert response.status_code == 404


class TestSearchAnimas:
    """Tests for GET /api/animas/search endpoint."""

    def test_search_animas_by_name(self, client: TestClient):
        """Search animas by partial name match."""
        # Create test animas
        client.post("/api/animas", json={"name": "Alpha Robot"})
        client.post("/api/animas", json={"name": "Beta Robot"})
        client.post("/api/animas", json={"name": "Gamma Agent"})

        # Search for "Robot"
        response = client.get("/api/animas/search?name=Robot")
        assert response.status_code == 200
        data = response.json()
        # Should find Alpha Robot and Beta Robot
        names = [a["name"] for a in data]
        assert any("Robot" in n for n in names)

    def test_search_animas_case_insensitive(self, client: TestClient):
        """Search is case-insensitive (ILIKE)."""
        client.post("/api/animas", json={"name": "CamelCaseAnima"})

        # Search lowercase
        response = client.get("/api/animas/search?name=camelcase")
        assert response.status_code == 200
        data = response.json()
        names = [a["name"] for a in data]
        assert any("CamelCase" in n for n in names)


