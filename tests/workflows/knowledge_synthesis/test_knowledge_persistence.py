"""
Tests for knowledge persistence step state handling.

Tests persist_knowledge() logic: empty responses, UUID parsing,
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
    persist_knowledge,
)


# ============================================================================
# Empty / skip paths
# ============================================================================

class TestEmptyResponse:
    """Empty LLM response -> no DB writes, clean result."""

    def test_empty_llm_response(self):
        """No items to persist returns zero counts."""
        result = persist_knowledge(
            memory_id=str(uuid4()),
            anima_id=str(uuid4()),
            llm_response=[],
        )

        assert result.knowledge_ids == []
        assert result.deleted_count == 0
        assert result.created_count == 0
        assert result.error is None

    def test_none_llm_response(self):
        """None llm_response treated as empty."""
        result = persist_knowledge(
            memory_id=str(uuid4()),
            anima_id=str(uuid4()),
            llm_response=None,
        )

        assert result.knowledge_ids == []
        assert result.created_count == 0


# ============================================================================
# UUID parsing errors
# ============================================================================

class TestUUIDParsing:
    """Invalid UUIDs produce error, no crash."""

    def test_invalid_memory_id(self):
        """Non-UUID memory_id returns error."""
        result = persist_knowledge(
            memory_id="not-a-uuid",
            anima_id=str(uuid4()),
            llm_response=[{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        )

        assert result.error is not None
        assert result.knowledge_ids == []

    def test_invalid_anima_id(self):
        """Non-UUID anima_id returns error."""
        result = persist_knowledge(
            memory_id=str(uuid4()),
            anima_id="bad-uuid",
            llm_response=[{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        )

        assert result.error is not None
        assert result.knowledge_ids == []


# ============================================================================
# RLS context failure
# ============================================================================

class TestRLSContextFailure:
    """Failure to resolve anima ownership produces error, no crash."""

    @patch("app.workflows.knowledge_synthesis.nodes.knowledge_persistence.get_user_id_for_anima")
    def test_anima_ownership_lookup_fails(self, mock_get_user):
        """get_user_id_for_anima raising returns error."""
        mock_get_user.side_effect = Exception("Anima not found")

        result = persist_knowledge(
            memory_id=str(uuid4()),
            anima_id=str(uuid4()),
            llm_response=[{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        )

        assert result.error is not None
        assert "Anima" in result.error
        assert result.knowledge_ids == []


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

        result = persist_knowledge(
            memory_id=str(uuid4()),
            anima_id=str(uuid4()),
            llm_response=[{"knowledge_type": "FACT", "content": "x" * 20, "summary": "test"}],
        )

        assert result.error is not None
        assert "Connection refused" in result.error
        assert result.knowledge_ids == []
