"""
Event Collection

Fetches all pending events since last memory for synthesis.
Events are serialized to plain dicts for LLM prompt construction.

Uses RLS context for multi-tenant security (read operations).
"""
import logging
from datetime import datetime
from uuid import UUID
from typing import List, Dict, Any

from app.domain.memory_operations import MemoryOperations
from app.domain.event_operations import EventOperations
from app.domain.anima_operations import AnimaOperations
from app.models.database.events import Event
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


def collect_pending_events(anima_id: UUID) -> List[Dict[str, Any]]:
    """
    Collect pending events for memory synthesis.

    Fetches events since last memory, serializes for prompt building.

    Returns:
        List of serialized event dicts
    """
    logger.info(f"Collecting pending events for anima {anima_id}")

    user_id = get_user_id_for_anima(anima_id)

    with session_with_rls_context(user_id) as session:
        baseline_time = _get_baseline_timestamp(session, anima_id)
        events = EventOperations.get_since(session, anima_id, baseline_time)
        events_data = _serialize_events(events)

    logger.info(f"Collected {len(events_data)} pending events for anima {anima_id}")
    return events_data


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
    Serialize Event objects to dictionaries.
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
            "event_type": event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
        }
        for event in events
    ]
