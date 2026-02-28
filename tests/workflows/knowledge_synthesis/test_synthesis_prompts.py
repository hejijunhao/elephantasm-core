"""
Tests for knowledge synthesis prompt building.

Tests prompts independently from LLM calls.
Covers: T-2 (knowledge synthesis prompt builder — no tests)
"""
import pytest
from app.workflows.knowledge_synthesis.prompts.synthesis import (
    build_knowledge_synthesis_prompt,
)


class TestBuildKnowledgeSynthesisPrompt:
    """Tests for build_knowledge_synthesis_prompt()."""

    def test_includes_memory_summary(self):
        """Prompt includes the memory summary."""
        memory = {
            "summary": "User prefers dark mode interfaces",
            "content": "Full content about UI preferences",
            "importance": 0.8,
            "confidence": 0.9,
        }

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "User prefers dark mode interfaces" in prompt

    def test_includes_memory_content(self):
        """Prompt includes the memory content."""
        memory = {
            "summary": "Summary",
            "content": "Detailed content about deployment strategy",
            "importance": 0.5,
            "confidence": 0.7,
        }

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "Detailed content about deployment strategy" in prompt

    def test_includes_importance_and_confidence(self):
        """Prompt includes importance and confidence scores."""
        memory = {
            "summary": "Test memory",
            "importance": 0.85,
            "confidence": 0.92,
        }

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "0.85" in prompt
        assert "0.92" in prompt

    def test_falls_back_to_summary_when_content_missing(self):
        """Uses summary as content fallback when content is None."""
        memory = {
            "summary": "Fallback summary content",
            "content": None,
            "importance": 0.5,
            "confidence": 0.5,
        }

        prompt = build_knowledge_synthesis_prompt(memory)

        # Summary should appear twice: once as summary, once as content
        assert prompt.count("Fallback summary content") == 2

    def test_handles_empty_memory(self):
        """Prompt handles memory with no fields gracefully."""
        memory = {}

        prompt = build_knowledge_synthesis_prompt(memory)

        # Should still produce a valid prompt
        assert "MEMORY SUMMARY" in prompt
        assert "MEMORY CONTENT" in prompt
        assert "unknown" in prompt  # Default for missing importance/confidence

    def test_includes_knowledge_type_definitions(self):
        """Prompt includes all five epistemic types."""
        memory = {"summary": "Test", "importance": 0.5, "confidence": 0.5}

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "FACT" in prompt
        assert "CONCEPT" in prompt
        assert "METHOD" in prompt
        assert "PRINCIPLE" in prompt
        assert "EXPERIENCE" in prompt

    def test_includes_json_output_format(self):
        """Prompt specifies JSON array output format."""
        memory = {"summary": "Test", "importance": 0.5, "confidence": 0.5}

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "knowledge_type" in prompt
        assert "content" in prompt
        assert "summary" in prompt
        assert "topic" in prompt
        assert "JSON array" in prompt

    def test_includes_empty_array_guidance(self):
        """Prompt mentions returning empty array when no knowledge extractable."""
        memory = {"summary": "Test"}

        prompt = build_knowledge_synthesis_prompt(memory)

        assert "[]" in prompt
