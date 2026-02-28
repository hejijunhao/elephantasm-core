"""
Memory Fetch Node

Loads Memory by ID with RLS context for knowledge extraction.
Validates Memory exists and not deleted, optionally fetches source Events.

⚠️ CRITICAL: Uses RLS context for multi-tenant security (read operations).
"""
from uuid import UUID
from typing import Dict, Any, List, Optional
from langsmith import traceable
from ..state import KnowledgeSynthesisState
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


@traceable(name="fetch_memory", tags=["db_read", "data_preparation", "rls"])
def fetch_memory_node(state: KnowledgeSynthesisState) -> dict:
    """
    Fetch Memory by ID with RLS context.

    Sync node (runs in thread pool via FastAPI).
    Validates Memory exists and not deleted, serializes for checkpointing.

    ⚠️ RLS Context: Even read operations use RLS for security.
    Ensures workflow can only access Memories for the Memory's owner.

    Args:
        state: Current workflow state with memory_id

    Returns:
        State updates:
        - memory_data: Serialized Memory dict (if valid)
        - source_events: Optional serialized Events (if INCLUDE_SOURCE_EVENTS=true)
        - skip_reason: "invalid_memory" if not found/deleted
        - error: Error message if invalid UUID or unexpected failure

    Raises:
        No exceptions raised - errors captured in state
    """
    memory_id_str = state["memory_id"]

    # Validate UUID format
    try:
        memory_id = UUID(memory_id_str)
    except (ValueError, AttributeError) as e:
        return {
            "error": f"{ERROR_INVALID_MEMORY_ID}: {str(e)}",
            "skip_reason": SKIP_REASON_INVALID_MEMORY,
        }

    # Get user_id for RLS context (bypass RLS for ownership lookup)
    try:
        # Chicken-egg problem: Need user_id to set RLS context, but need to query
        # Memory to get anima_id to get user_id. Solution: Use SECURITY DEFINER
        # bypass helper that queries directly for user_id.
        from app.core.rls_dependencies import get_entity_user_id_bypass_rls
        from app.core.database import SessionLocal

        with SessionLocal() as session:
            user_id = get_entity_user_id_bypass_rls(session, 'memory', memory_id)

        if not user_id:
            return {
                "error": ERROR_MEMORY_NOT_FOUND,
                "skip_reason": SKIP_REASON_INVALID_MEMORY,
            }

    except Exception as e:
        return {
            "error": f"Failed to resolve Memory ownership: {str(e)}",
            "skip_reason": SKIP_REASON_INVALID_MEMORY,
        }

    # Fetch Memory with RLS context (validates user owns Memory's Anima)
    try:
        with session_with_rls_context(user_id) as session:
            memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=False)

            if not memory:
                return {
                    "error": ERROR_MEMORY_NOT_FOUND,
                    "skip_reason": SKIP_REASON_INVALID_MEMORY,
                }

            # Serialize Memory for checkpointing
            memory_data = _serialize_memory(memory)

            # Optionally fetch source Events for additional context
            source_events_data = []
            if INCLUDE_SOURCE_EVENTS:
                source_events = _fetch_source_events(session, memory_id)
                source_events_data = _serialize_events(source_events)

    except Exception as e:
        return {
            "error": f"Database error fetching Memory: {str(e)}",
            "skip_reason": SKIP_REASON_INVALID_MEMORY,
        }

    return {
        "memory_data": memory_data,
        "source_events": source_events_data,
        "error": None,  # Clear any stale error from previous checkpoint
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _serialize_memory(memory: Memory) -> Dict[str, Any]:
    """
    Serialize Memory object to checkpoint-safe dictionary.

    Extracts fields needed for LLM knowledge extraction:
    - id, anima_id, summary, content, importance, confidence
    - time_start, time_end, state, meta

    Args:
        memory: Memory ORM object

    Returns:
        Serialized dict ready for JSON checkpointing
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
    Provides additional context for knowledge extraction (optional).

    Args:
        session: Database session with RLS context
        memory_id: Memory UUID

    Returns:
        List of Event objects (may be empty)
    """
    from app.domain.memory_event_operations import MemoryEventOperations

    # Get MemoryEvent links
    links = MemoryEventOperations.get_by_memory_id(session, memory_id)

    if not links:
        return []

    # Fetch Events by IDs
    event_ids = [link.event_id for link in links]
    events = []

    for event_id in event_ids:
        event = EventOperations.get_by_id(session, event_id, include_deleted=False)
        if event:
            events.append(event)

    return events


def _serialize_events(events: List[Event]) -> List[Dict[str, Any]]:
    """
    Serialize Event objects to checkpoint-safe dictionaries.

    Extracts fields useful for knowledge extraction context:
    - id, content, role, author, occurred_at

    Args:
        events: List of Event ORM objects

    Returns:
        List of serialized dicts
    """
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
