"""
Memory Persistence Node

Persists synthesized memory to database with provenance links.
Creates Memory record and MemoryEvent junction records in atomic transaction.
"""
from datetime import datetime, timezone
from uuid import UUID
from typing import List
from ..state import MemorySynthesisState
from app.domain.memory_operations import MemoryOperations
from app.domain.memory_event_operations import MemoryEventOperations
from app.models.database.memories import MemoryCreate, MemoryState
from app.models.database.memories_events import MemoryEventCreate
from app.core.database import get_db_session


def persist_memory_node(state: MemorySynthesisState) -> dict:
    # Persist synthesized memory and provenance links to database.
    # Extract required state
    llm_response = state.get("llm_response")
    pending_events = state.get("pending_events", [])
    anima_id = UUID(state["anima_id"])

    if not llm_response:
        raise ValueError("No LLM response to persist")

    if not pending_events:
        raise ValueError("No pending events for provenance")

    # Atomic transaction: Memory + MemoryEvent links
    with get_db_session() as session:
        # Create memory from LLM response
        memory = _create_memory(session, anima_id, llm_response, pending_events)

        # Create provenance links (bulk)
        links = _create_provenance_links(session, memory.id, pending_events)

        # Auto-committed by context manager

    return {
        "memory_id": str(memory.id),
        "provenance_links": [str(link.id) for link in links],
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _create_memory(session, anima_id: UUID, llm_response: dict, pending_events: list):
    # Create Memory record from LLM response.
    # Calculate time span from events
    time_start, time_end = _calculate_time_span(pending_events)

    # Build memory data
    memory_data = MemoryCreate(
        anima_id=anima_id,
        summary=llm_response["summary"],
        content=llm_response.get("content"),  # Optional
        importance=llm_response.get("importance"),  # Optional
        confidence=llm_response.get("confidence"),  # Optional
        state=MemoryState.ACTIVE,
        time_start=time_start,
        time_end=time_end,
    )

    # Create memory
    memory = MemoryOperations.create(session, memory_data)
    session.flush()  # Get memory.id for provenance links
    session.refresh(memory)

    return memory


def _create_provenance_links(session, memory_id: UUID, pending_events: list) -> List:
    # Create MemoryEvent provenance links (bulk).
    # Build link data for all events
    links_data = [
        MemoryEventCreate(
            memory_id=memory_id,
            event_id=UUID(event["id"]),
            link_strength=1.0,  # Default: all events equally weighted
        )
        for event in pending_events
    ]

    # Bulk create
    links = MemoryEventOperations.bulk_create(session, links_data)
    session.flush()

    return links


def _calculate_time_span(pending_events: list) -> tuple[datetime, datetime]:
    # Calculate time_start and time_end from events.
    # Parse timestamps
    timestamps = [
        datetime.fromisoformat(event["occurred_at"])
        for event in pending_events
        if event.get("occurred_at")
    ]

    if not timestamps:
        # Fallback: use current time for both
        now = datetime.now(timezone.utc)
        return now, now

    # time_start = earliest event, time_end = latest event
    time_start = min(timestamps)
    time_end = max(timestamps)

    return time_start, time_end
