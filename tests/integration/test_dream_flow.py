"""
Integration tests for Dream session/action API.

Tests cover:
- Create/complete/fail dream sessions (domain ops via admin session)
- Cancel running sessions via API
- has_running_session concurrency guard
- List sessions with pagination and status filter
- Get session by ID
- Get session with actions (eager load)
- List actions for a session
- Dream stats aggregation
- Session-action relationship integrity
- 404 for non-existent sessions

Note: POST /dreams/trigger requires FeatureGate + RequireActionAllowed
(subscription checks), so sessions are created via domain ops directly.
Query/cancel endpoints are tested through the API.
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import (
    DreamActionType,
    DreamPhase,
    DreamSession,
    DreamStatus,
    DreamTriggerType,
)
from tests.integration.conftest import get_admin_session


@pytest.fixture
def dream_session(test_anima: dict) -> dict:
    """Create a COMPLETED dream session with metrics via admin session."""
    admin = get_admin_session()
    try:
        anima_id = test_anima["id"]

        # Create session
        dream = DreamerOperations.create_session(
            admin,
            anima_id=anima_id,
            trigger_type=DreamTriggerType.MANUAL,
            skip_usage_tracking=True,
        )
        session_id = dream.id

        # Complete it with metrics
        dream.memories_reviewed = 10
        dream.memories_modified = 3
        dream.memories_created = 1
        dream.memories_archived = 2
        dream.memories_deleted = 1
        admin.flush()

        dream = DreamerOperations.complete_session(
            admin, session_id, summary="Test dream completed"
        )
        admin.commit()

        return {
            "id": str(dream.id),
            "anima_id": anima_id,
            "status": dream.status.value,
        }
    finally:
        admin.close()


@pytest.fixture
def running_session(test_anima: dict) -> dict:
    """Create a RUNNING dream session via admin session."""
    admin = get_admin_session()
    try:
        dream = DreamerOperations.create_session(
            admin,
            anima_id=test_anima["id"],
            trigger_type=DreamTriggerType.MANUAL,
            skip_usage_tracking=True,
        )
        admin.commit()

        return {
            "id": str(dream.id),
            "anima_id": test_anima["id"],
        }
    finally:
        admin.close()


@pytest.fixture
def session_with_actions(test_anima: dict) -> dict:
    """Create a dream session with actions via admin session."""
    admin = get_admin_session()
    try:
        anima_id = test_anima["id"]

        dream = DreamerOperations.create_session(
            admin,
            anima_id=anima_id,
            trigger_type=DreamTriggerType.MANUAL,
            skip_usage_tracking=True,
        )

        # Insert actions directly (domain memory ops need real memories,
        # so we use _record_action for controlled test data)
        mem_id_1 = uuid4()
        mem_id_2 = uuid4()

        DreamerOperations._record_action(
            admin,
            dream_session=dream,
            action_type=DreamActionType.UPDATE,
            phase=DreamPhase.LIGHT_SLEEP,
            source_memory_ids=[mem_id_1],
            before_state={"memories": [{"id": str(mem_id_1), "importance": 0.3}]},
            result_memory_ids=[mem_id_1],
            after_state={"memories": [{"id": str(mem_id_1), "importance": 0.1}]},
            reasoning=None,
        )
        DreamerOperations._record_action(
            admin,
            dream_session=dream,
            action_type=DreamActionType.ARCHIVE,
            phase=DreamPhase.LIGHT_SLEEP,
            source_memory_ids=[mem_id_2],
            before_state={"memories": [{"id": str(mem_id_2), "state": "ACTIVE"}]},
            result_memory_ids=[mem_id_2],
            after_state={"memories": [{"id": str(mem_id_2), "state": "DECAYING"}]},
            reasoning=None,
        )

        dream = DreamerOperations.complete_session(
            admin, dream.id, summary="Test with actions"
        )
        admin.commit()

        return {
            "id": str(dream.id),
            "anima_id": anima_id,
            "action_count": 2,
        }
    finally:
        admin.close()


class TestListDreamSessions:
    """Tests for GET /api/dreams/sessions."""

    def test_list_sessions_empty(self, client: TestClient, test_anima: dict):
        """List sessions for anima with no dreams returns empty list."""
        response = client.get(
            "/api/dreams/sessions", params={"anima_id": test_anima["id"]}
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_list_sessions_returns_sessions(
        self, client: TestClient, test_anima: dict, dream_session: dict
    ):
        """List sessions returns created sessions."""
        response = client.get(
            "/api/dreams/sessions", params={"anima_id": test_anima["id"]}
        )

        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) >= 1
        ids = [s["id"] for s in sessions]
        assert dream_session["id"] in ids

    def test_list_sessions_status_filter(
        self, client: TestClient, test_anima: dict, dream_session: dict
    ):
        """Filter sessions by status."""
        # Filter for COMPLETED — should find our session
        response = client.get(
            "/api/dreams/sessions",
            params={"anima_id": test_anima["id"], "status": "COMPLETED"},
        )

        assert response.status_code == 200
        sessions = response.json()
        assert all(s["status"] == "COMPLETED" for s in sessions)
        assert any(s["id"] == dream_session["id"] for s in sessions)

        # Filter for RUNNING — should not find our completed session
        response = client.get(
            "/api/dreams/sessions",
            params={"anima_id": test_anima["id"], "status": "RUNNING"},
        )

        assert response.status_code == 200
        sessions = response.json()
        assert not any(s["id"] == dream_session["id"] for s in sessions)

    def test_list_sessions_pagination(self, client: TestClient, test_anima: dict):
        """Pagination with limit and offset."""
        # Create multiple sessions
        admin = get_admin_session()
        try:
            for _ in range(3):
                dream = DreamerOperations.create_session(
                    admin,
                    anima_id=test_anima["id"],
                    trigger_type=DreamTriggerType.MANUAL,
                    skip_usage_tracking=True,
                )
                DreamerOperations.complete_session(
                    admin, dream.id, summary="Pagination test"
                )
            admin.commit()
        finally:
            admin.close()

        # Get first page
        r1 = client.get(
            "/api/dreams/sessions",
            params={"anima_id": test_anima["id"], "limit": 2, "offset": 0},
        )
        assert r1.status_code == 200
        assert len(r1.json()) == 2

        # Get second page
        r2 = client.get(
            "/api/dreams/sessions",
            params={"anima_id": test_anima["id"], "limit": 2, "offset": 2},
        )
        assert r2.status_code == 200
        assert len(r2.json()) >= 1

        # No overlap
        ids_1 = {s["id"] for s in r1.json()}
        ids_2 = {s["id"] for s in r2.json()}
        assert ids_1.isdisjoint(ids_2)


class TestGetDreamSession:
    """Tests for GET /api/dreams/sessions/{session_id}."""

    def test_get_session_success(
        self, client: TestClient, dream_session: dict
    ):
        """Get session by ID returns full session data."""
        response = client.get(f"/api/dreams/sessions/{dream_session['id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == dream_session["id"]
        assert data["anima_id"] == dream_session["anima_id"]
        assert data["status"] == "COMPLETED"
        assert data["summary"] == "Test dream completed"
        assert data["memories_reviewed"] == 10
        assert data["memories_modified"] == 3
        assert data["memories_created"] == 1
        assert data["memories_archived"] == 2
        assert data["memories_deleted"] == 1
        assert data["completed_at"] is not None

    def test_get_session_not_found(self, client: TestClient):
        """Get non-existent session returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/dreams/sessions/{fake_id}")

        assert response.status_code == 404


class TestGetSessionWithActions:
    """Tests for GET /api/dreams/sessions/{session_id}/with-actions."""

    def test_with_actions_success(
        self, client: TestClient, session_with_actions: dict
    ):
        """Get session with actions returns session + action list."""
        response = client.get(
            f"/api/dreams/sessions/{session_with_actions['id']}/with-actions"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == session_with_actions["id"]
        assert "actions" in data
        assert len(data["actions"]) == session_with_actions["action_count"]

        # Verify action structure
        action = data["actions"][0]
        assert "action_type" in action
        assert "phase" in action
        assert "source_memory_ids" in action
        assert "before_state" in action
        assert "created_at" in action

    def test_with_actions_empty(self, client: TestClient, dream_session: dict):
        """Session with no actions returns empty action list."""
        response = client.get(
            f"/api/dreams/sessions/{dream_session['id']}/with-actions"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["actions"] == []

    def test_with_actions_not_found(self, client: TestClient):
        """Non-existent session returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/dreams/sessions/{fake_id}/with-actions")

        assert response.status_code == 404


class TestListDreamActions:
    """Tests for GET /api/dreams/sessions/{session_id}/actions."""

    def test_list_actions(self, client: TestClient, session_with_actions: dict):
        """List actions returns all actions for session."""
        response = client.get(
            f"/api/dreams/sessions/{session_with_actions['id']}/actions"
        )

        assert response.status_code == 200
        actions = response.json()
        assert len(actions) == 2

        # Verify action types match what we created
        types = [a["action_type"] for a in actions]
        assert "UPDATE" in types
        assert "ARCHIVE" in types

        # Verify phases
        assert all(a["phase"] == "LIGHT_SLEEP" for a in actions)

    def test_list_actions_empty_session(
        self, client: TestClient, dream_session: dict
    ):
        """Session with no actions returns empty list."""
        response = client.get(
            f"/api/dreams/sessions/{dream_session['id']}/actions"
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_list_actions_not_found(self, client: TestClient):
        """Non-existent session returns 404."""
        fake_id = str(uuid4())
        response = client.get(f"/api/dreams/sessions/{fake_id}/actions")

        assert response.status_code == 404


class TestCancelDreamSession:
    """Tests for POST /api/dreams/sessions/{session_id}/cancel."""

    def test_cancel_running_session(
        self, client: TestClient, running_session: dict
    ):
        """Cancel a running session transitions to FAILED."""
        response = client.post(
            f"/api/dreams/sessions/{running_session['id']}/cancel"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FAILED"
        assert "Cancelled by user" in data["error_message"]
        assert data["completed_at"] is not None

    def test_cancel_completed_session_400(
        self, client: TestClient, dream_session: dict
    ):
        """Cancel a completed session returns 400."""
        response = client.post(
            f"/api/dreams/sessions/{dream_session['id']}/cancel"
        )

        assert response.status_code == 400
        assert "RUNNING" in response.json()["detail"]

    def test_cancel_not_found(self, client: TestClient):
        """Cancel non-existent session returns 404."""
        fake_id = str(uuid4())
        response = client.post(f"/api/dreams/sessions/{fake_id}/cancel")

        assert response.status_code == 404


class TestDreamStats:
    """Tests for GET /api/dreams/stats."""

    def test_stats_empty(self, client: TestClient, test_anima: dict):
        """Stats for anima with no dreams returns zeroes."""
        response = client.get(
            "/api/dreams/stats", params={"anima_id": test_anima["id"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_dreams"] == 0
        assert data["completed_dreams"] == 0
        assert data["failed_dreams"] == 0
        assert data["running_dreams"] == 0
        assert data["last_dream_at"] is None
        assert data["aggregate_metrics"]["memories_reviewed"] == 0

    def test_stats_with_sessions(
        self, client: TestClient, test_anima: dict, dream_session: dict
    ):
        """Stats reflect completed session metrics."""
        response = client.get(
            "/api/dreams/stats", params={"anima_id": test_anima["id"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_dreams"] >= 1
        assert data["completed_dreams"] >= 1
        assert data["last_dream_at"] is not None
        assert data["aggregate_metrics"]["memories_reviewed"] >= 10
        assert data["aggregate_metrics"]["memories_modified"] >= 3
        assert data["aggregate_metrics"]["memories_created"] >= 1
        assert data["aggregate_metrics"]["memories_archived"] >= 2
        assert data["aggregate_metrics"]["memories_deleted"] >= 1


class TestDomainOperations:
    """Tests for DreamerOperations domain methods via admin session."""

    def test_create_session(self, test_anima: dict):
        """Create session initializes with RUNNING status."""
        admin = get_admin_session()
        try:
            dream = DreamerOperations.create_session(
                admin,
                anima_id=test_anima["id"],
                trigger_type=DreamTriggerType.SCHEDULED,
                skip_usage_tracking=True,
            )
            admin.commit()

            assert dream.status == DreamStatus.RUNNING
            assert dream.trigger_type == DreamTriggerType.SCHEDULED
            assert str(dream.anima_id) == test_anima["id"]
            assert dream.memories_reviewed == 0
        finally:
            admin.close()

    def test_complete_session(self, test_anima: dict):
        """Complete session transitions to COMPLETED with summary."""
        admin = get_admin_session()
        try:
            dream = DreamerOperations.create_session(
                admin,
                anima_id=test_anima["id"],
                trigger_type=DreamTriggerType.MANUAL,
                skip_usage_tracking=True,
            )
            completed = DreamerOperations.complete_session(
                admin, dream.id, summary="All done"
            )
            admin.commit()

            assert completed.status == DreamStatus.COMPLETED
            assert completed.summary == "All done"
            assert completed.completed_at is not None
        finally:
            admin.close()

    def test_fail_session(self, test_anima: dict):
        """Fail session transitions to FAILED with error message."""
        admin = get_admin_session()
        try:
            dream = DreamerOperations.create_session(
                admin,
                anima_id=test_anima["id"],
                trigger_type=DreamTriggerType.MANUAL,
                skip_usage_tracking=True,
            )
            failed = DreamerOperations.fail_session(
                admin, dream.id, error_message="LLM timeout"
            )
            admin.commit()

            assert failed.status == DreamStatus.FAILED
            assert "LLM timeout" in failed.error_message
            assert failed.completed_at is not None
        finally:
            admin.close()

    def test_has_running_session(self, test_anima: dict):
        """has_running_session detects active dreams."""
        admin = get_admin_session()
        try:
            anima_id = test_anima["id"]

            # No sessions — should be False
            assert DreamerOperations.has_running_session(admin, anima_id) is False

            # Create RUNNING session
            dream = DreamerOperations.create_session(
                admin,
                anima_id=anima_id,
                trigger_type=DreamTriggerType.MANUAL,
                skip_usage_tracking=True,
            )
            admin.flush()
            assert DreamerOperations.has_running_session(admin, anima_id) is True

            # Complete it — should be False again
            DreamerOperations.complete_session(admin, dream.id, summary="Done")
            admin.flush()
            assert DreamerOperations.has_running_session(admin, anima_id) is False

            admin.commit()
        finally:
            admin.close()

    def test_cancel_only_running(self, test_anima: dict):
        """Cancel rejects non-RUNNING sessions."""
        admin = get_admin_session()
        try:
            dream = DreamerOperations.create_session(
                admin,
                anima_id=test_anima["id"],
                trigger_type=DreamTriggerType.MANUAL,
                skip_usage_tracking=True,
            )
            DreamerOperations.complete_session(admin, dream.id, summary="Done")
            admin.flush()

            with pytest.raises(ValueError, match="RUNNING"):
                DreamerOperations.cancel_session(admin, dream.id)

            admin.commit()
        finally:
            admin.close()

    def test_record_action_updates_metrics(self, test_anima: dict):
        """_record_action increments session metrics correctly."""
        admin = get_admin_session()
        try:
            dream = DreamerOperations.create_session(
                admin,
                anima_id=test_anima["id"],
                trigger_type=DreamTriggerType.MANUAL,
                skip_usage_tracking=True,
            )

            mem_id = uuid4()
            DreamerOperations._record_action(
                admin,
                dream_session=dream,
                action_type=DreamActionType.ARCHIVE,
                phase=DreamPhase.LIGHT_SLEEP,
                source_memory_ids=[mem_id],
                before_state={"memories": [{"id": str(mem_id)}]},
            )
            admin.flush()

            assert dream.memories_archived == 1

            DreamerOperations._record_action(
                admin,
                dream_session=dream,
                action_type=DreamActionType.DELETE,
                phase=DreamPhase.LIGHT_SLEEP,
                source_memory_ids=[uuid4()],
                before_state={"memories": [{}]},
            )
            admin.flush()

            assert dream.memories_deleted == 1
            admin.commit()
        finally:
            admin.close()
