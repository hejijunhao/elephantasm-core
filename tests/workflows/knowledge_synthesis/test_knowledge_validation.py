"""
Tests for knowledge synthesis validation and cleaning logic.

Tests _validate_and_clean_knowledge_item() independently from LLM/DB.
Covers: T-1 (knowledge synthesis workflow nodes — zero tests)

Note: Imports use sys.modules mock to avoid circular import through
app.services.llm (LLM client is not needed for validation tests).
"""
import sys
import pytest
from unittest.mock import MagicMock

# Pre-seed app.services.llm to break circular import chain.
# The knowledge_synthesis module imports get_llm_client at module level,
# but validation tests don't exercise LLM calls.
if "app.services.llm" not in sys.modules:
    mock_llm = MagicMock()
    sys.modules["app.services.llm"] = mock_llm

from app.workflows.knowledge_synthesis.nodes.knowledge_synthesis import (
    _validate_and_clean_knowledge_item,
)
from app.workflows.knowledge_synthesis.config import (
    MIN_CONTENT_LENGTH,
    MAX_CONTENT_LENGTH,
    MIN_SUMMARY_LENGTH,
    MAX_SUMMARY_LENGTH,
    DEFAULT_TOPIC,
)


# ============================================================================
# Valid items
# ============================================================================

class TestValidItems:
    """Happy path — valid Knowledge items pass validation."""

    def test_valid_fact(self):
        """Standard FACT item passes validation."""
        item = {
            "knowledge_type": "FACT",
            "content": "Elephantasm uses FastAPI for the backend",
            "summary": "Backend uses FastAPI",
            "topic": "Project Architecture",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert result["knowledge_type"] == "FACT"
        assert result["content"] == "Elephantasm uses FastAPI for the backend"
        assert result["summary"] == "Backend uses FastAPI"
        assert result["topic"] == "Project Architecture"

    def test_all_knowledge_types(self):
        """All five epistemic types pass validation."""
        for ktype in ["FACT", "CONCEPT", "METHOD", "PRINCIPLE", "EXPERIENCE"]:
            item = {
                "knowledge_type": ktype,
                "content": f"This is a valid {ktype.lower()} knowledge item",
                "summary": f"Valid {ktype.lower()}",
                "topic": "Test",
            }
            result = _validate_and_clean_knowledge_item(item, 0)
            assert result["knowledge_type"] == ktype

    def test_missing_topic_gets_default(self):
        """Missing topic field defaults to DEFAULT_TOPIC."""
        item = {
            "knowledge_type": "FACT",
            "content": "Some valid content here",
            "summary": "Valid summary",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert result["topic"] == DEFAULT_TOPIC

    def test_empty_topic_gets_default(self):
        """Empty string topic defaults to DEFAULT_TOPIC."""
        item = {
            "knowledge_type": "FACT",
            "content": "Some valid content here",
            "summary": "Valid summary",
            "topic": "   ",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert result["topic"] == DEFAULT_TOPIC

    def test_whitespace_stripped(self):
        """Content and summary whitespace is stripped."""
        item = {
            "knowledge_type": "FACT",
            "content": "  Content with spaces  ",
            "summary": "  Summary with spaces  ",
            "topic": "  Topic  ",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert result["content"] == "Content with spaces"
        assert result["summary"] == "Summary with spaces"
        assert result["topic"] == "Topic"


# ============================================================================
# Required field validation
# ============================================================================

class TestRequiredFields:
    """Missing required fields raise ValueError."""

    def test_missing_knowledge_type(self):
        """Missing knowledge_type raises ValueError."""
        item = {
            "content": "Some content",
            "summary": "Summary",
        }

        with pytest.raises(ValueError, match="knowledge_type"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_missing_content(self):
        """Missing content raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "summary": "Summary",
        }

        with pytest.raises(ValueError, match="content"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_missing_summary(self):
        """Missing summary raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "content": "Some content",
        }

        with pytest.raises(ValueError, match="summary"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_empty_knowledge_type(self):
        """Empty string knowledge_type raises ValueError."""
        item = {
            "knowledge_type": "",
            "content": "Some content",
            "summary": "Summary",
        }

        with pytest.raises(ValueError):
            _validate_and_clean_knowledge_item(item, 0)

    def test_empty_content(self):
        """Empty string content raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "content": "",
            "summary": "Summary",
        }

        with pytest.raises(ValueError):
            _validate_and_clean_knowledge_item(item, 0)

    def test_empty_summary(self):
        """Empty string summary raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "content": "Some content",
            "summary": "",
        }

        with pytest.raises(ValueError):
            _validate_and_clean_knowledge_item(item, 0)


# ============================================================================
# Knowledge type validation
# ============================================================================

class TestKnowledgeTypeValidation:
    """Invalid knowledge_type values are rejected."""

    def test_invalid_type_rejected(self):
        """Unrecognized type raises ValueError."""
        item = {
            "knowledge_type": "OPINION",
            "content": "Some valid content",
            "summary": "Valid summary",
        }

        with pytest.raises(ValueError, match="OPINION"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_lowercase_type_rejected(self):
        """Lowercase type is invalid (enum is uppercase)."""
        item = {
            "knowledge_type": "fact",
            "content": "Some valid content",
            "summary": "Valid summary",
        }

        with pytest.raises(ValueError):
            _validate_and_clean_knowledge_item(item, 0)


# ============================================================================
# Content length validation
# ============================================================================

class TestContentLength:
    """Content length constraints are enforced."""

    def test_content_too_short(self):
        """Content below MIN_CONTENT_LENGTH raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "content": "Hi",  # Too short
            "summary": "Valid summary",
        }

        with pytest.raises(ValueError, match="too short"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_content_at_min_length(self):
        """Content exactly at MIN_CONTENT_LENGTH passes."""
        item = {
            "knowledge_type": "FACT",
            "content": "x" * MIN_CONTENT_LENGTH,
            "summary": "Valid summary",
        }

        result = _validate_and_clean_knowledge_item(item, 0)
        assert len(result["content"]) == MIN_CONTENT_LENGTH

    def test_content_truncated_when_too_long(self):
        """Content above MAX_CONTENT_LENGTH is truncated with ellipsis."""
        long_content = "x" * (MAX_CONTENT_LENGTH + 100)
        item = {
            "knowledge_type": "FACT",
            "content": long_content,
            "summary": "Valid summary",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert len(result["content"]) == MAX_CONTENT_LENGTH
        assert result["content"].endswith("...")

    def test_content_at_max_length_not_truncated(self):
        """Content exactly at MAX_CONTENT_LENGTH is not truncated."""
        exact_content = "x" * MAX_CONTENT_LENGTH
        item = {
            "knowledge_type": "FACT",
            "content": exact_content,
            "summary": "Valid summary",
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert result["content"] == exact_content
        assert not result["content"].endswith("...")


# ============================================================================
# Summary length validation
# ============================================================================

class TestSummaryLength:
    """Summary length constraints are enforced."""

    def test_summary_too_short(self):
        """Summary below MIN_SUMMARY_LENGTH raises ValueError."""
        item = {
            "knowledge_type": "FACT",
            "content": "Some valid content here",
            "summary": "Hi",  # Too short (< 3)
        }

        with pytest.raises(ValueError, match="too short"):
            _validate_and_clean_knowledge_item(item, 0)

    def test_summary_truncated_when_too_long(self):
        """Summary above MAX_SUMMARY_LENGTH is truncated with ellipsis."""
        long_summary = "x" * (MAX_SUMMARY_LENGTH + 50)
        item = {
            "knowledge_type": "FACT",
            "content": "Some valid content here",
            "summary": long_summary,
        }

        result = _validate_and_clean_knowledge_item(item, 0)

        assert len(result["summary"]) == MAX_SUMMARY_LENGTH
        assert result["summary"].endswith("...")
