"""
Memories-Events API Routes

REST endpoints for managing Memory-Event provenance links (junction table).
Provides link creation, bulk operations, and link deletion.

Note: Query endpoints (get events for memory, get memories for event) are nested
under /api/memories/{id}/events and /api/events/{id}/memories for better REST semantics.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session
from pydantic import BaseModel

from app.core.rls_dependencies import get_db_with_rls
from app.domain.memory_event_operations import MemoryEventOperations
from app.models.database.memories_events import (
    MemoryEvent,
    MemoryEventCreate,
    MemoryEventRead
)


router = APIRouter(prefix="/memories-events", tags=["memories-events"])


# ═══════════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════════

class BulkLinkCreateRequest(BaseModel):
    """Request model for bulk link creation."""
    memory_id: UUID
    event_ids: List[UUID]
    link_strength: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════
# Endpoints - Link Management
# ═══════════════════════════════════════════════════════════════════

@router.post(
    "",
    response_model=MemoryEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create provenance link"
)
async def create_link(
    data: MemoryEventCreate,
    db: Session = Depends(get_db_with_rls)
) -> MemoryEventRead:
    """
    Create a single provenance link between a memory and an event.
    RLS policies automatically filter by authenticated user.

    Validates that both memory and event exist and belong to the same anima.

    Raises:
        404: Memory or Event not found (or not owned by user)
        400: Memory and Event belong to different animas, or duplicate link
    """
    link = MemoryEventOperations.create_link(db, data)  # No await!
    return MemoryEventRead.model_validate(link)


@router.post(
    "/bulk",
    response_model=List[MemoryEventRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create multiple links (batch operation)"
)
async def create_bulk_links(
    data: BulkLinkCreateRequest,
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryEventRead]:
    """
    Create multiple provenance links from one memory to multiple events.

    Optimized for Cortex when synthesizing a memory from 5-20 events.
    Performs batch validation (95% query reduction vs individual creates).

    Raises:
        404: Memory not found, or one or more Events not found
        400: Events belong to different Anima than Memory
    """
    links = MemoryEventOperations.create_bulk_links(  # No await!
        session=db,
        memory_id=data.memory_id,
        event_ids=data.event_ids,
        link_strength=data.link_strength
    )
    return [MemoryEventRead.model_validate(link) for link in links]


@router.get(
    "/memory/{memory_id}",
    response_model=List[MemoryEventRead],
    summary="Get all links for a memory"
)
async def get_links_for_memory(
    memory_id: UUID,
    limit: int = Query(100, ge=1, le=500, description="Max links to return"),
    min_strength: Optional[float] = Query(
        None, ge=0.0, le=1.0, description="Filter by minimum link strength"
    ),
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryEventRead]:
    """
    Get all provenance links for a memory (includes metadata like link_strength).

    Returns MemoryEvent objects with full link metadata.
    Ordered by link_strength DESC (high-strength links first).
    """
    links = MemoryEventOperations.get_links_for_memory(  # No await!
        session=db,
        memory_id=memory_id,
        limit=limit,
        min_strength=min_strength
    )
    return [MemoryEventRead.model_validate(link) for link in links]


@router.get(
    "/memory/{memory_id}/count",
    response_model=int,
    summary="Count events for a memory"
)
async def count_events_for_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> int:
    """
    Count how many events contributed to a memory.

    Useful for analytics and pagination.
    """
    count = MemoryEventOperations.count_events_for_memory(db, memory_id)  # No await!
    return count


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete provenance link"
)
async def delete_link(
    link_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> None:
    """
    Delete a provenance link by ID (hard delete - links are cheap to recreate).

    Raises:
        404: Link not found
    """
    MemoryEventOperations.delete_link(db, link_id)  # No await!
    return None


@router.delete(
    "/memory/{memory_id}",
    response_model=int,
    summary="Delete all links for a memory"
)
async def delete_links_for_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> int:
    """
    Delete all provenance links for a memory (cleanup operation).

    Useful for memory re-synthesis or cleanup.
    Returns count of deleted links.
    """
    count = MemoryEventOperations.delete_links_for_memory(db, memory_id)  # No await!
    return count


@router.delete(
    "/event/{event_id}",
    response_model=int,
    summary="Delete all links for an event"
)
async def delete_links_for_event(
    event_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> int:
    """
    Delete all provenance links for an event (cleanup operation).

    Useful when event is being permanently removed.
    Returns count of deleted links.
    """
    count = MemoryEventOperations.delete_links_for_event(db, event_id)  # No await!
    return count
