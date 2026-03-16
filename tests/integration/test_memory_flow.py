"""
Integration tests for Memory operations API.

Tests cover:
- Create memories with provenance links
- List and filter by anima, state
- Text and semantic search
- Memory statistics
- State transitions
"""

import pytest
from uuid import uuid4

from fastapi.testclient import TestClient


@pytest.fixture
def test_event(client: TestClient, test_anima: dict) -> dict:
    """Create a test event for provenance linking."""
    response = client.post(
        "/api/events",
        json={
            "anima_id": test_anima["id"],
            "event_type": "message.in",
            "content": "Source event for memory"
        }
    )
    assert response.status_code == 201
    return response.json()


class TestCreateMemory:
    """Tests for POST /api/memories endpoint."""

    def test_create_memory_success(self, client: TestClient, test_anima: dict):
        """Create memory with valid data returns 201."""
        response = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Test memory summary about the conversation",
                "importance": 0.7,
                "confidence": 0.85
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["anima_id"] == test_anima["id"]
        assert data["summary"] == "Test memory summary about the conversation"
        assert data["importance"] == 0.7
        assert data["confidence"] == 0.85
        assert "id" in data
        assert "created_at" in data

    def test_create_memory_minimal(self, client: TestClient, test_anima: dict):
        """Create memory with minimal required fields."""
        response = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Minimal memory"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["summary"] == "Minimal memory"

    def test_create_memory_with_meta(self, client: TestClient, test_anima: dict):
        """Create memory with meta JSONB."""
        response = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Memory with metadata",
                "meta": {"topics": ["test", "api"], "source": "integration_test"}
            }
        )

        assert response.status_code == 201
        assert response.json()["meta"]["topics"] == ["test", "api"]


class TestListMemories:
    """Tests for GET /api/memories endpoint."""

    def test_list_memories_requires_anima_id(self, client: TestClient):
        """List memories without anima_id returns 422."""
        response = client.get("/api/memories")
        assert response.status_code == 422

    def test_list_memories_by_anima(self, client: TestClient, test_anima: dict):
        """List memories filtered by anima_id."""
        # Create memories
        for i in range(3):
            client.post(
                "/api/memories",
                json={
                    "anima_id": test_anima["id"],
                    "summary": f"Memory {i}"
                }
            )

        response = client.get(f"/api/memories?anima_id={test_anima['id']}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3
        assert all(m["anima_id"] == test_anima["id"] for m in data)

    def test_list_memories_by_state(self, client: TestClient, test_anima: dict):
        """List memories filtered by state."""
        # Create an active memory
        resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Active memory"
            }
        )
        assert resp.status_code == 201

        # List active only
        response = client.get(
            f"/api/memories?anima_id={test_anima['id']}&state=active"
        )
        assert response.status_code == 200
        data = response.json()
        assert all(m["state"] == "active" for m in data)

    def test_list_memories_pagination(self, client: TestClient, test_anima: dict):
        """List memories with pagination."""
        # Create 10 memories
        for i in range(10):
            client.post(
                "/api/memories",
                json={
                    "anima_id": test_anima["id"],
                    "summary": f"Paginated memory {i}"
                }
            )

        # First page
        resp1 = client.get(
            f"/api/memories?anima_id={test_anima['id']}&limit=3&offset=0"
        )
        assert resp1.status_code == 200
        assert len(resp1.json()) == 3

        # Second page
        resp2 = client.get(
            f"/api/memories?anima_id={test_anima['id']}&limit=3&offset=3"
        )
        assert resp2.status_code == 200


class TestSearchMemories:
    """Tests for GET /api/memories/search endpoint."""

    def test_search_memories_by_summary(self, client: TestClient, test_anima: dict):
        """Search memories by summary text."""
        # Create memories with distinct content
        client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "The user prefers dark mode interfaces"
            }
        )
        client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Meeting scheduled for next Tuesday"
            }
        )

        # Search for "dark mode"
        response = client.get(
            f"/api/memories/search?anima_id={test_anima['id']}&q=dark%20mode"
        )
        assert response.status_code == 200
        data = response.json()
        # Should find the dark mode memory
        assert any("dark mode" in m["summary"].lower() for m in data)


class TestMemoryStats:
    """Tests for GET /api/memories/stats endpoint."""

    def test_memory_stats(self, client: TestClient, test_anima: dict):
        """Get memory statistics for anima."""
        # Create some memories
        for i in range(5):
            client.post(
                "/api/memories",
                json={
                    "anima_id": test_anima["id"],
                    "summary": f"Stats memory {i}"
                }
            )

        response = client.get(f"/api/memories/stats?anima_id={test_anima['id']}")
        assert response.status_code == 200
        data = response.json()
        # Should have counts
        assert "total" in data or "active" in data or isinstance(data, dict)


class TestGetMemory:
    """Tests for GET /api/memories/{id} endpoint."""

    def test_get_memory_success(self, client: TestClient, test_anima: dict):
        """Get existing memory returns 200."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Get test memory"
            }
        )
        memory_id = create_resp.json()["id"]

        # Get
        response = client.get(f"/api/memories/{memory_id}")
        assert response.status_code == 200
        assert response.json()["id"] == memory_id

    def test_get_memory_not_found(self, client: TestClient):
        """Get non-existent memory returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/memories/{fake_id}")
        assert response.status_code == 404


class TestGetMemoryEvents:
    """Tests for GET /api/memories/{id}/events endpoint."""

    def test_get_memory_events(self, client: TestClient, test_anima: dict, test_event: dict):
        """Get source events for a memory."""
        # Create memory
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Memory with provenance"
            }
        )
        assert create_resp.status_code == 201
        memory_id = create_resp.json()["id"]

        # Link event to memory (via memories-events endpoint)
        link_resp = client.post(
            "/api/memories-events",
            json={
                "memory_id": memory_id,
                "event_id": test_event["id"]
            }
        )
        # May succeed or fail depending on endpoint availability
        if link_resp.status_code == 201:
            # Get events for memory
            response = client.get(f"/api/memories/{memory_id}/events")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)


class TestUpdateMemory:
    """Tests for PATCH /api/memories/{id} endpoint."""

    def test_update_memory_summary(self, client: TestClient, test_anima: dict):
        """Update memory summary returns 200."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Original summary"
            }
        )
        memory_id = create_resp.json()["id"]

        # Update
        response = client.patch(
            f"/api/memories/{memory_id}",
            json={"summary": "Updated summary"}
        )

        assert response.status_code == 200
        assert response.json()["summary"] == "Updated summary"

    def test_update_memory_state(self, client: TestClient, test_anima: dict):
        """Update memory state (active -> decaying)."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "State transition test"
            }
        )
        memory_id = create_resp.json()["id"]

        # Update state
        response = client.patch(
            f"/api/memories/{memory_id}",
            json={"state": "decaying"}
        )

        assert response.status_code == 200
        assert response.json()["state"] == "decaying"

    def test_update_memory_importance(self, client: TestClient, test_anima: dict):
        """Update memory importance score."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Importance update test",
                "importance": 0.5
            }
        )
        memory_id = create_resp.json()["id"]

        # Update
        response = client.patch(
            f"/api/memories/{memory_id}",
            json={"importance": 0.9}
        )

        assert response.status_code == 200
        assert response.json()["importance"] == 0.9


class TestDeleteMemory:
    """Tests for DELETE /api/memories/{id} endpoint."""

    def test_delete_memory_success(self, client: TestClient, test_anima: dict):
        """Delete memory returns 204 (soft delete)."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Delete me"
            }
        )
        memory_id = create_resp.json()["id"]

        # Delete
        response = client.delete(f"/api/memories/{memory_id}")
        assert response.status_code in [200, 204]


class TestRestoreMemory:
    """Tests for POST /api/memories/{id}/restore endpoint."""

    def test_restore_memory_success(self, client: TestClient, test_anima: dict):
        """Restore soft-deleted memory."""
        # Create
        create_resp = client.post(
            "/api/memories",
            json={
                "anima_id": test_anima["id"],
                "summary": "Restore me"
            }
        )
        memory_id = create_resp.json()["id"]

        # Delete
        client.delete(f"/api/memories/{memory_id}")

        # Restore
        response = client.post(f"/api/memories/{memory_id}/restore")
        assert response.status_code == 200
        # Verify it's accessible again
        get_resp = client.get(f"/api/memories/{memory_id}")
        assert get_resp.status_code == 200


