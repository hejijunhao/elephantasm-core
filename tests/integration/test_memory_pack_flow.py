"""Integration tests for MemoryPack CRUD, statistics, and retention.

Tests the memory pack persistence/query/stats/delete endpoints and domain operations.
Pack compilation is tested separately in test_pack_flow.py — this covers the
MemoryPack entity lifecycle after compilation.

Finding: T-7 (MemoryPack creation/statistics — no tests)
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.integration.conftest import get_admin_session
from app.domain.anima_operations import AnimaOperations
from app.domain.memory_pack_operations import MemoryPackOperations
from app.models.database.animas import AnimaCreate
from app.models.database.memory_pack import MemoryPack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_pack(test_anima: dict) -> dict:
    """Create a single memory pack via domain operations."""
    admin = get_admin_session()
    try:
        pack = MemoryPack(
            anima_id=test_anima["id"],
            query="test query",
            preset_name="conversational",
            session_memory_count=3,
            knowledge_count=2,
            long_term_memory_count=1,
            has_identity=True,
            token_count=500,
            max_tokens=4000,
            content={"context": "test context string", "config": {}},
            compiled_at=datetime.now(timezone.utc),
        )
        pack = MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
        admin.commit()
        return {
            "id": str(pack.id),
            "anima_id": str(pack.anima_id),
            "token_count": pack.token_count,
            "has_identity": pack.has_identity,
        }
    finally:
        admin.close()


@pytest.fixture
def multiple_packs(test_anima: dict) -> list[dict]:
    """Create 3 packs with varied stats for aggregation testing."""
    admin = get_admin_session()
    packs = []
    try:
        configs = [
            {"token_count": 300, "session_memory_count": 2, "knowledge_count": 1,
             "long_term_memory_count": 0, "has_identity": True,
             "compiled_at": datetime.now(timezone.utc) - timedelta(minutes=3)},
            {"token_count": 600, "session_memory_count": 4, "knowledge_count": 3,
             "long_term_memory_count": 2, "has_identity": False,
             "compiled_at": datetime.now(timezone.utc) - timedelta(minutes=2)},
            {"token_count": 900, "session_memory_count": 6, "knowledge_count": 5,
             "long_term_memory_count": 4, "has_identity": True,
             "compiled_at": datetime.now(timezone.utc) - timedelta(minutes=1)},
        ]
        for cfg in configs:
            pack = MemoryPack(
                anima_id=test_anima["id"],
                query="multi test",
                preset_name="conversational",
                max_tokens=4000,
                content={"context": "test"},
                **cfg,
            )
            pack = MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
            packs.append({"id": str(pack.id), "token_count": pack.token_count})
        admin.commit()
        return packs
    finally:
        admin.close()


# ---------------------------------------------------------------------------
# API Tests: List Memory Packs
# ---------------------------------------------------------------------------

class TestListMemoryPacks:
    """Tests for GET /api/animas/{anima_id}/memory-packs."""

    def test_list_packs_empty(self, client: TestClient, test_anima: dict):
        """Anima with no packs returns empty list."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_packs_returns_packs(
        self, client: TestClient, test_anima: dict, multiple_packs: list[dict]
    ):
        """List returns created packs."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3
        ids = [p["id"] for p in data]
        for pack in multiple_packs:
            assert pack["id"] in ids

    def test_list_packs_pagination(
        self, client: TestClient, test_anima: dict, multiple_packs: list[dict]
    ):
        """Pagination limits results and offset skips."""
        page1 = client.get(
            f"/api/animas/{test_anima['id']}/memory-packs",
            params={"limit": 2, "offset": 0},
        )
        page2 = client.get(
            f"/api/animas/{test_anima['id']}/memory-packs",
            params={"limit": 2, "offset": 2},
        )
        assert page1.status_code == 200
        assert page2.status_code == 200
        assert len(page1.json()) == 2
        # No overlap
        ids1 = {p["id"] for p in page1.json()}
        ids2 = {p["id"] for p in page2.json()}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# API Tests: Get Latest Memory Pack
# ---------------------------------------------------------------------------

class TestGetLatestMemoryPack:
    """Tests for GET /api/animas/{anima_id}/memory-packs/latest."""

    def test_latest_empty(self, client: TestClient, test_anima: dict):
        """Returns null when no packs exist."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs/latest")
        assert response.status_code == 200
        assert response.json() is None

    def test_latest_returns_most_recent(
        self, client: TestClient, test_anima: dict, multiple_packs: list[dict]
    ):
        """Returns the pack with the most recent compiled_at."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs/latest")
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        # Most recent pack has token_count=900 (last in our configs)
        assert data["token_count"] == 900


# ---------------------------------------------------------------------------
# API Tests: Memory Pack Stats
# ---------------------------------------------------------------------------

class TestGetMemoryPackStats:
    """Tests for GET /api/animas/{anima_id}/memory-packs/stats."""

    def test_stats_empty(self, client: TestClient, test_anima: dict):
        """Empty anima returns zeroed stats."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_packs"] == 0
        assert data["avg_token_count"] == 0.0
        assert data["avg_session_memories"] == 0.0
        assert data["identity_usage_rate"] == 0.0

    def test_stats_with_packs(
        self, client: TestClient, test_anima: dict, multiple_packs: list[dict]
    ):
        """Stats reflect correct averages across packs."""
        response = client.get(f"/api/animas/{test_anima['id']}/memory-packs/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_packs"] == 3
        # avg token: (300+600+900)/3 = 600
        assert data["avg_token_count"] == pytest.approx(600.0, abs=1)
        # avg session memories: (2+4+6)/3 = 4
        assert data["avg_session_memories"] == pytest.approx(4.0, abs=0.1)
        # avg knowledge: (1+3+5)/3 = 3
        assert data["avg_knowledge"] == pytest.approx(3.0, abs=0.1)
        # identity usage: 2/3 = 66.67%
        assert data["identity_usage_rate"] == pytest.approx(66.67, abs=1)


# ---------------------------------------------------------------------------
# API Tests: Get / Delete by ID
# ---------------------------------------------------------------------------

class TestGetMemoryPackById:
    """Tests for GET /api/memory-packs/{pack_id}."""

    def test_get_pack_success(
        self, client: TestClient, memory_pack: dict
    ):
        """Returns pack data by ID."""
        response = client.get(f"/api/memory-packs/{memory_pack['id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == memory_pack["id"]
        assert data["token_count"] == memory_pack["token_count"]
        assert "content" in data

    def test_get_pack_not_found(self, client: TestClient):
        """Returns 404 for non-existent pack."""
        fake_id = str(uuid4())
        response = client.get(f"/api/memory-packs/{fake_id}")
        assert response.status_code == 404


class TestDeleteMemoryPack:
    """Tests for DELETE /api/memory-packs/{pack_id}."""

    def test_delete_pack_success(self, client: TestClient, memory_pack: dict):
        """Delete returns 204."""
        response = client.delete(f"/api/memory-packs/{memory_pack['id']}")
        assert response.status_code == 204

    def test_delete_pack_not_found(self, client: TestClient):
        """Delete returns 404 for non-existent pack."""
        fake_id = str(uuid4())
        response = client.delete(f"/api/memory-packs/{fake_id}")
        assert response.status_code == 404

    def test_deleted_pack_inaccessible(self, client: TestClient, memory_pack: dict):
        """After deletion, GET returns 404."""
        client.delete(f"/api/memory-packs/{memory_pack['id']}")
        response = client.get(f"/api/memory-packs/{memory_pack['id']}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Domain Tests: MemoryPackOperations
# ---------------------------------------------------------------------------

class TestMemoryPackDomain:
    """Tests for MemoryPackOperations domain methods."""

    def test_create_pack(self, test_anima: dict):
        """Create persists pack and returns with ID."""
        admin = get_admin_session()
        try:
            pack = MemoryPack(
                anima_id=test_anima["id"],
                token_count=250,
                max_tokens=4000,
                content={"context": "domain test"},
                compiled_at=datetime.now(timezone.utc),
            )
            result = MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
            admin.commit()
            assert result.id is not None
            assert result.token_count == 250
        finally:
            admin.close()

    def test_get_by_anima_newest_first(self, test_anima: dict, multiple_packs: list[dict]):
        """get_by_anima returns packs ordered by compiled_at desc."""
        admin = get_admin_session()
        try:
            packs = MemoryPackOperations.get_by_anima(admin, test_anima["id"])
            assert len(packs) >= 3
            # Verify descending order by compiled_at
            for i in range(len(packs) - 1):
                assert packs[i].compiled_at >= packs[i + 1].compiled_at
        finally:
            admin.close()

    def test_count_by_anima(self, test_anima: dict, multiple_packs: list[dict]):
        """count_by_anima returns correct count."""
        admin = get_admin_session()
        try:
            count = MemoryPackOperations.count_by_anima(admin, test_anima["id"])
            assert count >= 3
        finally:
            admin.close()

    def test_delete_old_packs_retention(self, test_anima: dict):
        """delete_old_packs keeps only the most recent N packs."""
        admin = get_admin_session()
        try:
            # Create 5 packs
            for i in range(5):
                pack = MemoryPack(
                    anima_id=test_anima["id"],
                    token_count=100 * (i + 1),
                    max_tokens=4000,
                    content={"context": f"retention test {i}"},
                    compiled_at=datetime.now(timezone.utc) - timedelta(minutes=5 - i),
                )
                MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
            admin.commit()

            # Keep only 2
            deleted = MemoryPackOperations.delete_old_packs(admin, test_anima["id"], keep_count=2)
            admin.commit()
            assert deleted >= 3  # At least 3 deleted (5 - 2)

            remaining = MemoryPackOperations.count_by_anima(admin, test_anima["id"])
            assert remaining == 2
        finally:
            admin.close()

    def test_enforce_retention(self, test_anima: dict):
        """enforce_retention deletes oldest packs beyond limit."""
        admin = get_admin_session()
        try:
            # Create 4 packs
            for i in range(4):
                pack = MemoryPack(
                    anima_id=test_anima["id"],
                    token_count=100 * (i + 1),
                    max_tokens=4000,
                    content={"context": f"enforce test {i}"},
                    compiled_at=datetime.now(timezone.utc) - timedelta(minutes=4 - i),
                )
                MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
            admin.commit()

            deleted = MemoryPackOperations.enforce_retention(
                admin, test_anima["id"], max_packs=2
            )
            admin.commit()
            assert deleted >= 2

            remaining = MemoryPackOperations.count_by_anima(admin, test_anima["id"])
            assert remaining == 2
        finally:
            admin.close()

    def test_delete_by_id(self, test_anima: dict):
        """delete_by_id removes pack, returns True. Missing returns False."""
        admin = get_admin_session()
        try:
            pack = MemoryPack(
                anima_id=test_anima["id"],
                token_count=100,
                max_tokens=4000,
                content={},
                compiled_at=datetime.now(timezone.utc),
            )
            pack = MemoryPackOperations.create(admin, pack, skip_usage_tracking=True)
            admin.commit()
            pack_id = pack.id

            assert MemoryPackOperations.delete_by_id(admin, pack_id) is True
            admin.commit()
            assert MemoryPackOperations.get_by_id(admin, pack_id) is None
            assert MemoryPackOperations.delete_by_id(admin, pack_id) is False
        finally:
            admin.close()
