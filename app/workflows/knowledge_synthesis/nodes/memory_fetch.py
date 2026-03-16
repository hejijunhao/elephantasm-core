"""
Memory Fetch

Loads Memory by ID with RLS context for knowledge extraction.
Validates Memory exists and not deleted, optionally fetches source Events.

Uses RLS context for multi-tenant security (read operations).
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID
from typing import Dict, Any, List, Optional

from ..config import (
    ERROR_MEMORY_NOT_FOUND,
    ERROR_INVALID_MEMORY_ID,
    SKIP_REASON_INVALID_MEMORY,
    INCLUDE_SOURCE_EVENTS,
)
from app.domain.memory_operations import MemoryOperations
from app.domain.event_operations import EventOperations
from app.models.database.memories import Memory
from app.models.database.events import Event
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


@dataclass
class MemoryFetchResult:
    """Result from memory fetch step."""

    memory_data: Optional[Dict[str, Any]] = None
    source_events: List[Dict[str, Any]] = field(default_factory=list)
    skip_reason: Optional[str] = None
    error: Optional[str] = None


def fetch_memory(memory_id: str) -> MemoryFetchResult:
    """
    Fetch Memory by ID with RLS context.

    Validates Memory exists and not deleted, serializes for prompt building.
    Errors are captured in the result, not raised.

    Args:
        memory_id: UUID string of the memory to fetch

    Returns:
        MemoryFetchResult with memory_data (if valid) or skip_reason/error
    """
    logger.info(f"Fetching memory {memory_id} for knowledge synthesis")

    # Validate UUID format
    try:
        memory_uuid = UUID(memory_id)
    except (ValueError, AttributeError) as e:
        return MemoryFetchResult(
            error=f"{ERROR_INVALID_MEMORY_ID}: {str(e)}",
            skip_reason=SKIP_REASON_INVALID_MEMORY,
        )

    # Get user_id for RLS context (bypass RLS for ownership lookup)
    try:
        from app.core.rls_dependencies import get_entity_user_id_bypass_rls
        from app.core.database import SessionLocal

        with SessionLocal() as session:
            user_id = get_entity_user_id_bypass_rls(session, 'memory', memory_uuid)

        if not user_id:
            return MemoryFetchResult(
                error=ERROR_MEMORY_NOT_FOUND,
                skip_reason=SKIP_REASON_INVALID_MEMORY,
            )

    except Exception as e:
        return MemoryFetchResult(
            error=f"Failed to resolve Memory ownership: {str(e)}",
            skip_reason=SKIP_REASON_INVALID_MEMORY,
        )

    # Fetch Memory with RLS context (validates user owns Memory's Anima)
    try:
        with session_with_rls_context(user_id) as session:
            memory = MemoryOperations.get_by_id(session, memory_uuid, include_deleted=False)

            if not memory:
                return MemoryFetchResult(
                    error=ERROR_MEMORY_NOT_FOUND,
                    skip_reason=SKIP_REASON_INVALID_MEMORY,
                )

            # Serialize Memory
            memory_data = _serialize_memory(memory)

            # Optionally fetch source Events for additional context
            source_events_data = []
            if INCLUDE_SOURCE_EVENTS:
                source_events = _fetch_source_events(session, memory_uuid)
                source_events_data = _serialize_events(source_events)

    except Exception as e:
        return MemoryFetchResult(
            error=f"Database error fetching Memory: {str(e)}",
            skip_reason=SKIP_REASON_INVALID_MEMORY,
        )

    logger.info(f"Memory {memory_id} fetched successfully")

    return MemoryFetchResult(
        memory_data=memory_data,
        source_events=source_events_data,
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _serialize_memory(memory: Memory) -> Dict[str, Any]:
    """
    Serialize Memory object to dictionary.

    Extracts fields needed for LLM knowledge extraction:
    - id, anima_id, summary, content, importance, confidence
    - time_start, time_end, state, meta
    """
    return {
        "id": str(memory.id),
        "anima_id": str(memory.anima_id),
        "summary": memory.summary,
        "content": memory.content,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "time_start": memory.time_start.isoformat() if memory.time_start else None,
        "time_end": memory.time_end.isoformat() if memory.time_end else None,
        "state": memory.state.value if hasattr(memory.state, 'value') else memory.state,
        "meta": memory.meta or {},
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def _fetch_source_events(session, memory_id: UUID) -> List[Event]:
    """
    Fetch Events that created this Memory (provenance).
    Queries MemoryEvent junction table to find linked Events.
    """
    from app.domain.memory_event_operations import MemoryEventOperations

    links = MemoryEventOperations.get_by_memory_id(session, memory_id)

    if not links:
        return []

    event_ids = [link.event_id for link in links]
    events = []

    for event_id in event_ids:
        event = EventOperations.get_by_id(session, event_id, include_deleted=False)
        if event:
            events.append(event)

    return events


def _serialize_events(events: List[Event]) -> List[Dict[str, Any]]:
    """Serialize Event objects to dictionaries for prompt context."""
    return [
        {
            "id": str(event.id),
            "content": event.content,
            "role": event.role,
            "author": event.author,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "event_type": event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
        }
        for event in events
    ]
