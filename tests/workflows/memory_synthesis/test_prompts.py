"""
Tests for memory synthesis prompt building.

Tests prompts independently from LLM calls.
"""
import pytest
from app.workflows.memory_synthesis.prompts.synthesis import (
    build_memory_synthesis_prompt,
    _format_event
)


def test_build_memory_synthesis_prompt():
    """Test prompt building with multiple events."""
    events = [
        {
            "content": "How do I integrate the API?",
            "summary": "API integration question",
            "role": "user",
            "author": "john@example.com",
            "occurred_at": "2025-10-27T10:00:00Z"
        },
        {
            "content": "You can use our REST API...",
            "summary": "API integration explanation",
            "role": "assistant",
            "author": "gpt-4",
            "occurred_at": "2025-10-27T10:01:00Z"
        }
    ]

    prompt = build_memory_synthesis_prompt(events)

    # Verify prompt contains key elements
    assert "Synthesize a memory from these events" in prompt
    assert "API integration question" in prompt
    assert "API integration explanation" in prompt
    assert "john@example.com" in prompt
    assert "gpt-4" in prompt
    assert "2025-10-27T10:00:00Z" in prompt
    assert "Respond with JSON" in prompt
    assert "summary" in prompt
    assert "importance" in prompt
    assert "confidence" in prompt


def test_format_event_with_summary():
    """Test event formatting prefers summary over content."""
    event = {
        "content": "This is a very long content that would be truncated",
        "summary": "Short summary",
        "role": "user",
        "author": "alice@example.com",
        "occurred_at": "2025-10-27T10:00:00Z"
    }

    formatted = _format_event(event, 1)

    assert "[1]" in formatted
    assert "2025-10-27T10:00:00Z" in formatted
    assert "user" in formatted
    assert "alice@example.com" in formatted
    assert "Short summary" in formatted
    assert "very long content" not in formatted  # Should not use content if summary exists


def test_format_event_without_summary():
    """Test event formatting uses content when summary missing."""
    event = {
        "content": "Event content",
        "role": "assistant",
        "author": "claude",
        "occurred_at": "2025-10-27T10:00:00Z"
    }

    formatted = _format_event(event, 2)

    assert "[2]" in formatted
    assert "assistant" in formatted
    assert "claude" in formatted
    assert "Event content" in formatted


def test_format_event_truncates_long_content():
    """Test event formatting truncates content over 200 chars."""
    long_content = "a" * 300
    event = {
        "content": long_content,
        "occurred_at": "2025-10-27T10:00:00Z"
    }

    formatted = _format_event(event, 1)

    # Should truncate to 200 chars
    assert len(event["content"]) == 300
    assert "a" * 200 in formatted
    assert "a" * 201 not in formatted


def test_format_event_handles_missing_fields():
    """Test event formatting handles missing optional fields gracefully."""
    event = {
        "content": "Minimal event"
    }

    formatted = _format_event(event, 1)

    assert "[1]" in formatted
    assert "unknown" in formatted  # Default for missing role/author/timestamp
    assert "Minimal event" in formatted
