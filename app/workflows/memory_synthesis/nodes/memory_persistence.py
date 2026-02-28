"""
Memory Persistence Node

Persists synthesized memory to database with provenance links.
Creates Memory record and MemoryEvent junction records in atomic transaction.

⚠️ CRITICAL: Uses RLS context for multi-tenant security.
Memory + provenance links created in single transaction (proper ACID compliance).
"""
from datetime import datetime, timezone
from uuid import UUID
from typing import List
from langsmith import traceable
from ..state import MemorySynthesisState
from app.domain.memory_operations import MemoryOperations
from app.domain.memory_event_operations import MemoryEventOperations
from app.models.database.memories import MemoryCreate, MemoryState
from app.models.database.memories_events import MemoryEventCreate
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context


@traceable(name="persist_memory", tags=["db_write", "provenance"])
def persist_memory_node(state: MemorySynthesisState) -> dict:
    """
    Persist synthesized memory and provenance links to database.

    ⚠️ ATOMIC TRANSACTION: Memory + provenance created as single unit of work.
    This is CORRECT ARCHITECTURAL DESIGN (not just RLS requirement).

    RLS Context:
    - Fetches user_id from anima (lookup without RLS)
    - Sets RLS context for all subsequent operations
    - Ensures memory belongs to correct user (database enforces)

    Atomicity:
    - Memory creation and provenance linking in single transaction
    - Either both succeed or both fail (no orphaned records)
    - flush() pattern keeps transaction open between operations
    """
    # Extract required state
    llm_response = state.get("llm_response")
    pending_events = state.get("pending_events", [])
    anima_id = UUID(state["anima_id"])

    if not llm_response:
        raise ValueError("No LLM response to persist")

    if not pending_events:
        raise ValueError("No pending events for provenance")

    # Get user_id for RLS context (lookup without RLS)
    user_id = get_user_id_for_anima(anima_id)

    # Atomic transaction with RLS context
    with session_with_rls_context(user_id) as session:
        # Create memory from LLM response
        memory = _create_memory(session, anima_id, llm_response, pending_events)

        # Create provenance links (same transaction = atomicity guaranteed)
        links = _create_provenance_links(session, memory.id, pending_events)

        # Generate embedding for semantic search (best-effort, don't fail synthesis)
        embedding_generated = _generate_embedding(session, memory.id)

        # Auto-commit on context exit (all-or-nothing)

    return {
        "memory_id": str(memory.id),
        "provenance_links": [str(link.id) for link in links],
        "embedding_generated": embedding_generated,
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


def _generate_embedding(session, memory_id: UUID) -> bool:
    """
    Generate embedding for newly created memory.

    Best-effort: logs warning on failure but doesn't raise.
    Embedding can be regenerated later via bulk endpoint if needed.
    """
    import structlog
    logger = structlog.get_logger()

    try:
        MemoryOperations.generate_embedding(session, memory_id)
        logger.info("memory_embedding_generated", memory_id=str(memory_id))
        return True
    except Exception as e:
        # Log but don't fail - embedding is optional enhancement
        logger.warning(
            "memory_embedding_failed",
            memory_id=str(memory_id),
            error=str(e)
        )
        return False
