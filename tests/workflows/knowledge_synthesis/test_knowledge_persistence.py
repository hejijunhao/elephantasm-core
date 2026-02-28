"""
Tests for knowledge persistence node state handling.

Tests persist_knowledge_node() logic: empty responses, UUID parsing,
deduplication branching. Uses mocks for RLS/DB — DB writes are covered
by integration tests.

Covers: T-1 (knowledge synthesis workflow nodes — zero tests)

Note: Imports use sys.modules mock to avoid circular import through
app.services.llm (LLM client is not needed for persistence tests).
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

# Pre-seed app.services.llm to break circular import chain.
if "app.services.llm" not in sys.modules:
    sys.modules["app.services.llm"] = MagicMock()

from app.workflows.knowledge_synthesis.nodes.knowledge_persistence import (
    persist_knowledge_node,
)


# ============================================================================
# Empty / skip paths
# ============================================================================

class TestEmptyResponse:
    """Empty LLM response → no DB writes, clean state."""

    def test_empty_llm_response(self):
        """No items to persist returns zero counts."""
        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": str(uuid4())},
            "llm_response": [],
        }

        result = persist_knowledge_node(state)

        assert result["knowledge_ids"] == []
        assert result["deleted_count"] == 0
        assert result["created_count"] == 0
        assert result["error"] is None

    def test_missing_llm_response(self):
        """Missing llm_response key treated as empty."""
        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": str(uuid4())},
        }

        result = persist_knowledge_node(state)

        assert result["knowledge_ids"] == []
        assert result["created_count"] == 0

    def test_none_llm_response(self):
        """None llm_response treated as empty."""
        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": str(uuid4())},
            "llm_response": None,
        }

        result = persist_knowledge_node(state)

        assert result["knowledge_ids"] == []
        assert result["created_count"] == 0


# ============================================================================
# UUID parsing errors
# ============================================================================

class TestUUIDParsing:
    """Invalid UUIDs in state produce error, no crash."""

    def test_invalid_memory_id(self):
        """Non-UUID memory_id returns error."""
        state = {
            "memory_id": "not-a-uuid",
            "memory_data": {"anima_id": str(uuid4())},
            "llm_response": [{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        }

        result = persist_knowledge_node(state)

        assert result["error"] is not None
        assert result["knowledge_ids"] == []

    def test_missing_anima_id_in_memory_data(self):
        """Missing anima_id in memory_data returns error."""
        state = {
            "memory_id": str(uuid4()),
            "memory_data": {},
            "llm_response": [{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        }

        result = persist_knowledge_node(state)

        assert result["error"] is not None
        assert result["knowledge_ids"] == []

    def test_invalid_anima_id(self):
        """Non-UUID anima_id returns error."""
        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": "bad-uuid"},
            "llm_response": [{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        }

        result = persist_knowledge_node(state)

        assert result["error"] is not None
        assert result["knowledge_ids"] == []


# ============================================================================
# RLS context failure
# ============================================================================

class TestRLSContextFailure:
    """Failure to resolve anima ownership produces error, no crash."""

    @patch("app.workflows.knowledge_synthesis.nodes.knowledge_persistence.get_user_id_for_anima")
    def test_anima_ownership_lookup_fails(self, mock_get_user):
        """get_user_id_for_anima raising returns error."""
        mock_get_user.side_effect = Exception("Anima not found")

        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": str(uuid4())},
            "llm_response": [{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        }

        result = persist_knowledge_node(state)

        assert result["error"] is not None
        assert "Anima" in result["error"]
        assert result["knowledge_ids"] == []


# ============================================================================
# DB write failure
# ============================================================================

class TestDBWriteFailure:
    """DB errors during persistence produce error, no crash."""

    @patch("app.workflows.knowledge_synthesis.nodes.knowledge_persistence.get_user_id_for_anima")
    @patch("app.workflows.knowledge_synthesis.nodes.knowledge_persistence.session_with_rls_context")
    def test_session_context_error(self, mock_session_ctx, mock_get_user):
        """Exception inside session_with_rls_context returns error."""
        mock_get_user.return_value = uuid4()
        mock_session_ctx.side_effect = Exception("Connection refused")

        state = {
            "memory_id": str(uuid4()),
            "memory_data": {"anima_id": str(uuid4())},
            "llm_response": [{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        }

        result = persist_knowledge_node(state)

        assert result["error"] is not None
        assert "Connection refused" in result["error"]
        assert result["knowledge_ids"] == []
