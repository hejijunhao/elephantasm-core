"""Tests for auto Knowledge Synthesis hook."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
import sys

from app.services.hooks.auto_knowledge_synthesis import (
    _trigger_auto_knowledge_synthesis_async,
    trigger_auto_knowledge_synthesis,
)


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_success():
    """Should invoke workflow and log success when Knowledge created."""
    memory_id = str(uuid4())

    # Mock the workflow module and graph function
    mock_get_graph = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "knowledge_ids": ["uuid1", "uuid2", "uuid3"],
            "created_count": 3,
            "skip_reason": None,
            "error": None,
        }
    )
    mock_get_graph.return_value = mock_graph

    # Inject mock module into sys.modules to avoid circular import
    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(get_knowledge_synthesis_graph=mock_get_graph)}
    ):
        # Trigger synthesis (should not raise)
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        # Verify workflow invoked correctly
        mock_get_graph.assert_called_once()
        mock_graph.ainvoke.assert_called_once_with(
            {"memory_id": memory_id},
            config={"configurable": {"thread_id": f"knowledge-{memory_id}"}},
        )


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_skipped():
    """Should log skip reason when workflow skips extraction."""
    memory_id = str(uuid4())

    # Mock workflow to skip
    mock_get_graph = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "knowledge_ids": [],
            "created_count": 0,
            "skip_reason": "insufficient_content",
            "error": None,
        }
    )
    mock_get_graph.return_value = mock_graph

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(get_knowledge_synthesis_graph=mock_get_graph)}
    ):
        # Should not raise (fire-and-forget)
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        # Verify invoked
        mock_get_graph.assert_called_once()


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_error():
    """Should log error without raising when workflow fails."""
    memory_id = str(uuid4())

    # Mock workflow to raise error
    mock_get_graph = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(side_effect=Exception("LLM API timeout"))
    mock_get_graph.return_value = mock_graph

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(get_knowledge_synthesis_graph=mock_get_graph)}
    ):
        # Should not raise (fire-and-forget pattern)
        await _trigger_auto_knowledge_synthesis_async(memory_id)
        # If we get here, error was caught and logged


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_async_workflow_error_in_result():
    """Should log workflow error when returned in result state."""
    memory_id = str(uuid4())

    # Mock workflow to return error in state
    mock_get_graph = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "knowledge_ids": [],
            "created_count": 0,
            "skip_reason": None,
            "error": "Invalid memory content",
        }
    )
    mock_get_graph.return_value = mock_graph

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(get_knowledge_synthesis_graph=mock_get_graph)}
    ):
        # Should not raise
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        # Verify invoked
        mock_get_graph.assert_called_once()


def test_trigger_auto_knowledge_synthesis_creates_task():
    """Should create asyncio task for background execution."""
    memory_id = str(uuid4())

    with patch("asyncio.create_task") as mock_create_task:
        mock_task = MagicMock()
        mock_create_task.return_value = mock_task

        # Trigger synthesis
        result = trigger_auto_knowledge_synthesis(memory_id)

        # Verify task created
        mock_create_task.assert_called_once()
        assert result == mock_task


@pytest.mark.asyncio
async def test_trigger_auto_knowledge_synthesis_multiple_knowledge_items():
    """Should handle multiple Knowledge items correctly."""
    memory_id = str(uuid4())

    # Mock workflow with many Knowledge items
    knowledge_ids = [str(uuid4()) for _ in range(10)]
    mock_get_graph = AsyncMock()
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(
        return_value={
            "knowledge_ids": knowledge_ids,
            "created_count": 10,
            "skip_reason": None,
            "error": None,
        }
    )
    mock_get_graph.return_value = mock_graph

    with patch.dict(
        sys.modules,
        {"app.workflows.knowledge_synthesis": MagicMock(get_knowledge_synthesis_graph=mock_get_graph)}
    ):
        # Should handle large result set
        await _trigger_auto_knowledge_synthesis_async(memory_id)

        # Verify invoked
        mock_get_graph.assert_called_once()
