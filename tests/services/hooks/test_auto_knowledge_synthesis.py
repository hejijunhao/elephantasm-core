"""Tests for auto Knowledge Synthesis hook."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
import sys

from app.services.hooks.auto_knowledge_synthesis import (
    _trigger_auto_knowledge_synthesis_async,
    trigger_auto_knowledge_synthesis,
)


def _make_mock_result(**kwargs):
    """Create a mock KnowledgeSynthesisResult with given attributes."""
    mock = MagicMock()
    defaults = {
        "knowledge_ids": [],
        "created_count": 0,
        "skip_reason": None,
        "error": None,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_success():
    """Should invoke pipeline and log success when Knowledge created."""
    memory_id = str(uuid4())

    mock_result = _make_mock_result(
        knowledge_ids=["uuid1", "uuid2", "uuid3"],
        created_count=3,
    )
    mock_run = AsyncMock(return_value=mock_result)

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(run_knowledge_synthesis=mock_run)}
    ):
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        mock_run.assert_called_once_with(memory_id)


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_skipped():
    """Should log skip reason when pipeline skips extraction."""
    memory_id = str(uuid4())

    mock_result = _make_mock_result(skip_reason="insufficient_content")
    mock_run = AsyncMock(return_value=mock_result)

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(run_knowledge_synthesis=mock_run)}
    ):
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        mock_run.assert_called_once_with(memory_id)


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_error():
    """Should log error without raising when pipeline fails."""
    memory_id = str(uuid4())

    mock_run = AsyncMock(side_effect=Exception("LLM API timeout"))

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(run_knowledge_synthesis=mock_run)}
    ):
        # Should not raise (fire-and-forget pattern)
        await _trigger_auto_knowledge_synthesis_async(memory_id)


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_workflow_error_in_result():
    """Should log workflow error when returned in result."""
    memory_id = str(uuid4())

    mock_result = _make_mock_result(error="Invalid memory content")
    mock_run = AsyncMock(return_value=mock_result)

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(run_knowledge_synthesis=mock_run)}
    ):
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        mock_run.assert_called_once_with(memory_id)


def test_trigger_auto_knowledge_synthesis_creates_task():
    """Should create asyncio task for background execution."""
    memory_id = str(uuid4())

    with patch("asyncio.create_task") as mock_create_task, \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.ENABLE_BACKGROUND_JOBS = True
        mock_task = MagicMock()
        mock_create_task.return_value = mock_task

        result = trigger_auto_knowledge_synthesis(memory_id)

        mock_create_task.assert_called_once()
        assert result == mock_task


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_multiple_knowledge_items():
    """Should handle multiple Knowledge items correctly."""
    memory_id = str(uuid4())

    knowledge_ids = [str(uuid4()) for _ in range(10)]
    mock_result = _make_mock_result(
        knowledge_ids=knowledge_ids,
        created_count=10,
    )
    mock_run = AsyncMock(return_value=mock_result)

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(run_knowledge_synthesis=mock_run)}
    ):
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        mock_run.assert_called_once_with(memory_id)
