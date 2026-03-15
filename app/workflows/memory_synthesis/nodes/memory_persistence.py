"""
Memory Persistence

Persists synthesized memory to database with provenance links.
Creates Memory record and MemoryEvent junction records in atomic transaction.

Uses RLS context for multi-tenant security.
Memory + provenance links created in single transaction (proper ACID compliance).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID
from typing import Dict, Any, List

from app.domain.memory_operations import MemoryOperations
from app.domain.memory_event_operations import MemoryEventOperations
from app.models.database.memories import MemoryCreate, MemoryState
from app.models.database.memories_events import MemoryEventCreate
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


@dataclass
class MemoryPersistenceResult:
    """Result from memory persistence."""

    memory_id: str = ""
    provenance_links: list[str] = field(default_factory=list)
    embedding_generated: bool = False


def persist_memory(
    anima_id: UUID,
    pending_events: List[Dict[str, Any]],
    llm_response: Dict[str, Any],
) -> MemoryPersistenceResult:
    """
    Persist synthesized memory and provenance links to database.

    ATOMIC TRANSACTION: Memory + provenance created as single unit of work.
    Either both succeed or both fail (no orphaned records).
    """
    if not llm_response:
        raise ValueError("No LLM response to persist")

    if not pending_events:
        raise ValueError("No pending events for provenance")

    logger.info(f"Persisting memory for anima {anima_id}")

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

    logger.info(f"Memory {memory.id} persisted for anima {anima_id} with {len(links)} provenance links")

    return MemoryPersistenceResult(
        memory_id=str(memory.id),
        provenance_links=[str(link.id) for link in links],
        embedding_generated=embedding_generated,
    )


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
    try:
        MemoryOperations.generate_embedding(session, memory_id)
        logger.info(f"Embedding generated for memory {memory_id}")
        return True
    except Exception as e:
        # Log but don't fail - embedding is optional enhancement
        logger.warning(f"Embedding generation failed for memory {memory_id}: {e}")
        return False
