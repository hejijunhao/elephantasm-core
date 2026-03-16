"""Events API endpoints.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlmodel import Session
from sqlalchemy.exc import IntegrityError

from app.core.rls_dependencies import get_db_with_rls
from app.api.deps import RequireActionAllowed, SubscriptionContext
from app.domain.event_operations import EventOperations
from app.domain.memory_event_operations import MemoryEventOperations
from app.models.database.events import EventCreate, EventRead, EventUpdate
from app.models.database.memories import MemoryRead
from app.core.config import settings
from app.services.scheduler import get_memory_synthesis_scheduler


router = APIRouter(prefix="/events", tags=["events"])


@router.post(
    "",
    response_model=EventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create event"
)
async def create_event(
    data: EventCreate,
    background_tasks: BackgroundTasks,
    ctx: SubscriptionContext = Depends(RequireActionAllowed("create_event")),
    db: Session = Depends(get_db_with_rls)
) -> EventRead:
    """Create new event. Validates Anima FK, auto-defaults occurred_at, generates dedupe_key if needed.

    Optional fields: role (user/assistant/system/tool), author (identifier), summary, session_id, meta, etc.

    After event creation, triggers background check for memory synthesis threshold.
    Subject to monthly event limit based on plan tier.
    """
    try:
        event = EventOperations.create(db, data)  # No await!

        # Trigger synthesis check in background (non-blocking)
        if settings.ENABLE_BACKGROUND_JOBS:
            scheduler = get_memory_synthesis_scheduler()
            background_tasks.add_task(
                scheduler.check_and_enqueue_if_needed,
                event.anima_id
            )

        return EventRead.model_validate(event)
    except IntegrityError as e:
        # Likely duplicate dedupe_key
        if "dedupe_key" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate event (dedupe_key conflict)"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database integrity error"
        )


@router.get(
    "",
    response_model=List[EventRead],
    summary="List events"
)
async def list_events(
    anima_id: UUID = Query(..., description="Anima UUID to filter by"),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    min_importance: Optional[float] = Query(None, ge=0.0, le=1.0, description="Min importance score"),
    include_deleted: bool = Query(False, description="Include soft-deleted events"),
    db: Session = Depends(get_db_with_rls)
) -> List[EventRead]:
    """
    List events with filters. RLS policies automatically filter by authenticated user.
    Returns only events for animas owned by current user.

    If session_id provided, returns chronological order (ASC), otherwise recent-first (DESC).
    """
    if session_id:
        # Session-specific: chronological order
        events = EventOperations.get_by_session(  # No await!
            db, anima_id, session_id, include_deleted,
            limit=limit, offset=offset, event_type=event_type,
            min_importance=min_importance,
        )
    else:
        # General query: recent-first order
        events = EventOperations.get_recent(  # No await!
            db, anima_id, limit, offset, event_type, session_id, min_importance, include_deleted
        )

    return [EventRead.model_validate(event) for event in events]


@router.get(
    "/{event_id}",
    response_model=EventRead,
    summary="Get event by ID"
)
async def get_event(
    event_id: UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted events"),
    db: Session = Depends(get_db_with_rls)
) -> EventRead:
    """Get specific event by UUID."""
    event = EventOperations.get_by_id(db, event_id, include_deleted)  # No await!
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found"
        )

    return EventRead.model_validate(event)


@router.get(
    "/{event_id}/memories",
    response_model=List[MemoryRead],
    summary="Get memories for event"
)
async def get_event_memories(
    event_id: UUID,
    limit: int = Query(50, ge=1, le=200, description="Max memories to return"),
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryRead]:
    """
    Get all memories synthesized from this event (provenance query).

    Returns Memory objects ordered by link creation time (most recent first).
    Filters out soft-deleted memories.
    """
    memories = MemoryEventOperations.get_memories_for_event(  # No await!
        session=db,
        event_id=event_id,
        limit=limit
    )
    return [MemoryRead.model_validate(memory) for memory in memories]


@router.patch(
    "/{event_id}",
    response_model=EventRead,
    summary="Update event"
)
async def update_event(
    event_id: UUID,
    data: EventUpdate,
    db: Session = Depends(get_db_with_rls)
) -> EventRead:
    """Update event (partial). Can update role, author, summary, importance_score, metadata, is_deleted."""
    event = EventOperations.update(db, event_id, data)  # No await!
    return EventRead.model_validate(event)


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete event"
)
async def delete_event(
    event_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> None:
    """Soft delete event (mark as deleted, preserve for provenance)."""
    EventOperations.soft_delete(db, event_id)  # No await!
