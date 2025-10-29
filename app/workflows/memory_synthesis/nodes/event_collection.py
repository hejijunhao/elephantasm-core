"""
Event Collection Node

Fetches all pending events since last memory for synthesis.
Events are serialized for checkpoint persistence.
"""
from datetime import datetime
from uuid import UUID
from typing import List, Dict, Any
from ..state import MemorySynthesisState
from app.domain.memory_operations import MemoryOperations
from app.domain.event_operations import EventOperations
from app.domain.anima_operations import AnimaOperations
from app.models.database.events import Event
from app.core.database import get_db_session


def collect_pending_events_node(state: MemorySynthesisState) -> dict:
    """
    Collect pending events for memory synthesis.
    Sync node (runs in thread pool).
    Fetches events since last memory, serializes for checkpointing.
    """
    anima_id = UUID(state["anima_id"])

    with get_db_session() as session:
        baseline_time = _get_baseline_timestamp(session, anima_id)
        events = EventOperations.get_since(session, anima_id, baseline_time)
        events_data = _serialize_events(events)

    return {
        "pending_events": events_data,
        "event_count": len(events_data),
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _get_baseline_timestamp(session, anima_id: UUID) -> datetime:
    """
    Get baseline timestamp for event collection.
    Returns last memory timestamp, or anima creation time if no memories exist.
    """
    last_memory_time = MemoryOperations.get_last_memory_time(session, anima_id)

    if last_memory_time:
        return last_memory_time

    # Fallback: anima creation time
    anima = AnimaOperations.get_by_id(session, anima_id)
    if not anima:
        raise ValueError(f"Anima {anima_id} not found")

    return anima.created_at


def _serialize_events(events: List[Event]) -> List[Dict[str, Any]]:
    """
    Serialize Event objects to checkpoint-safe dictionaries.
    Extracts only fields needed for LLM synthesis:
    - id, content, summary, role, author, occurred_at, event_type
    """
    return [
        {
            "id": str(event.id),
            "content": event.content,
            "summary": event.summary,
            "role": event.role,
            "author": event.author,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "event_type": event.event_type.value if event.event_type else None,
        }
        for event in events
    ]
