"""
Memory API Routes

REST endpoints for Memory entity CRUD and queries.
All routes are thin HTTP adapters - business logic in MemoryOperations.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from pydantic import BaseModel

from app.core.rls_dependencies import get_db_with_rls
from app.models.database.memories import (
    Memory,
    MemoryCreate,
    MemoryRead,
    MemoryUpdate,
    MemoryState
)
from app.models.database.events import Event, EventRead
from app.domain.memory_operations import MemoryOperations
from app.domain.memory_event_operations import MemoryEventOperations


router = APIRouter(prefix="/memories", tags=["memories"])


# ═══════════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════════

class MemoryStatsResponse(BaseModel):
    """Response model for memory statistics."""
    anima_id: UUID
    total: Optional[int] = None
    active: Optional[int] = None
    decaying: Optional[int] = None
    archived: Optional[int] = None
    state: Optional[MemoryState] = None
    count: Optional[int] = None


class SemanticSearchRequest(BaseModel):
    """Request model for semantic search."""
    anima_id: UUID
    query: str
    limit: int = 10
    threshold: float = 0.7
    state: Optional[MemoryState] = MemoryState.ACTIVE


class MemoryWithScore(BaseModel):
    """Memory with similarity score."""
    memory: MemoryRead
    score: float


class BulkEmbeddingResponse(BaseModel):
    """Response for bulk embedding generation."""
    status: str
    anima_id: UUID
    processed: int


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("", response_model=MemoryRead, status_code=201)
async def create_memory(
    data: MemoryCreate,
    db: Session = Depends(get_db_with_rls)
) -> MemoryRead:
    """
    Create new memory with Anima FK validation.

    Raises:
        404: Anima not found
        422: Validation error (importance/confidence out of range)
    """
    memory = MemoryOperations.create(db, data)  # No await!
    return memory


@router.get("", response_model=List[MemoryRead])
async def list_memories(
    anima_id: UUID,
    state: Optional[MemoryState] = None,
    limit: int = Query(50, ge=1, le=200, description="Max results (1-200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    include_deleted: bool = False,
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryRead]:
    """
    List memories for anima (paginated, filterable by state).
    RLS policies automatically filter by authenticated user.
    Returns only memories for animas owned by current user.

    Ordered by time_end DESC, created_at DESC (most recent first).
    """
    memories = MemoryOperations.get_by_anima(  # No await!
        session=db,
        anima_id=anima_id,
        limit=limit,
        offset=offset,
        state=state,
        include_deleted=include_deleted
    )
    return memories


@router.get("/search", response_model=List[MemoryRead])
async def search_memories(
    anima_id: UUID,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=200, description="Max results (1-200)"),
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryRead]:
    """
    Search memories by summary text (case-insensitive partial match).

    Ordered by importance DESC (most important matches first).
    """
    memories = MemoryOperations.search_by_summary(  # No await!
        session=db,
        anima_id=anima_id,
        summary_query=q,
        limit=limit
    )
    return memories


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    anima_id: UUID,
    state: Optional[MemoryState] = None,
    db: Session = Depends(get_db_with_rls)
) -> MemoryStatsResponse:
    """
    Get memory count statistics by anima and state.

    Without state filter: Returns total + breakdown by all states.
    With state filter: Returns count for that specific state only.
    """
    if state:
        # Single state count
        count = MemoryOperations.count_by_anima(db, anima_id, state=state)  # No await!
        return MemoryStatsResponse(
            anima_id=anima_id,
            state=state,
            count=count
        )
    else:
        # All state counts
        total = MemoryOperations.count_by_anima(db, anima_id)  # No await!
        active = MemoryOperations.count_by_anima(  # No await!
            db, anima_id, state=MemoryState.ACTIVE
        )
        decaying = MemoryOperations.count_by_anima(  # No await!
            db, anima_id, state=MemoryState.DECAYING
        )
        archived = MemoryOperations.count_by_anima(  # No await!
            db, anima_id, state=MemoryState.ARCHIVED
        )

        return MemoryStatsResponse(
            anima_id=anima_id,
            total=total,
            active=active,
            decaying=decaying,
            archived=archived
        )


@router.get("/{memory_id}", response_model=MemoryRead)
async def get_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> MemoryRead:
    # Get single memory by ID.
    memory = MemoryOperations.get_by_id(db, memory_id)  # No await!
    if not memory:
        raise HTTPException(
            status_code=404,
            detail=f"Memory {memory_id} not found"
        )
    return memory


@router.patch("/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: UUID,
    data: MemoryUpdate,
    db: Session = Depends(get_db_with_rls)
) -> MemoryRead:
    # Partial update of memory fields.
    # Only provided fields are updated (sparse update).
    memory = MemoryOperations.update(db, memory_id, data)  # No await!
    return memory


@router.get("/{memory_id}/events", response_model=List[EventRead])
async def get_memory_events(
    memory_id: UUID,
    limit: int = Query(100, ge=1, le=500, description="Max events to return"),
    db: Session = Depends(get_db_with_rls)
) -> List[EventRead]:
    """
    Get all events that contributed to this memory (provenance query).
    Returns Event objects ordered by link creation time (most recent first).
    Filters out soft-deleted events.
    """
    events = MemoryEventOperations.get_events_for_memory(  # No await!
        session=db,
        memory_id=memory_id,
        limit=limit
    )
    return [EventRead.model_validate(event) for event in events]


@router.post("/{memory_id}/restore", response_model=MemoryRead)
async def restore_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> MemoryRead:
    # Restore soft-deleted memory.
    memory = MemoryOperations.restore(db, memory_id)  # No await!
    return memory


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> None:
    # Soft delete memory (provenance preservation).
    # Does not remove from database, only sets is_deleted flag.
    MemoryOperations.soft_delete(db, memory_id)  # No await!
    return None


# ═══════════════════════════════════════════════════════════════════
# Semantic Search Endpoints (pgVector)
# ═══════════════════════════════════════════════════════════════════

@router.post("/search/semantic", response_model=List[MemoryWithScore])
async def semantic_search(
    request: SemanticSearchRequest,
    db: Session = Depends(get_db_with_rls)
) -> List[MemoryWithScore]:
    """
    Search memories by semantic similarity using vector embeddings.
    Converts query text to embedding, then finds similar memories using cosine similarity.
    Requires memories to have embeddings generated (via synthesis or bulk generation).
    """
    from app.services.embeddings import get_embedding_provider

    # Generate embedding for query
    provider = get_embedding_provider()
    query_embedding = provider.embed_text(request.query)

    # Search for similar memories
    results = MemoryOperations.search_similar(
        session=db,
        anima_id=request.anima_id,
        query_embedding=query_embedding,
        limit=request.limit,
        threshold=request.threshold,
        state=request.state
    )

    return [
        MemoryWithScore(memory=MemoryRead.model_validate(memory), score=score)
        for memory, score in results
    ]


@router.post("/{memory_id}/embedding", response_model=MemoryRead)
async def generate_memory_embedding(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> MemoryRead:
    """
    Generate embedding for a single memory.
    Uses OpenAI text-embedding-3-small (1536 dimensions).
    Overwrites existing embedding if present.
    """
    try:
        memory = MemoryOperations.generate_embedding(db, memory_id)
        return MemoryRead.model_validate(memory)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/embeddings/bulk", response_model=BulkEmbeddingResponse)
async def bulk_generate_embeddings(
    anima_id: UUID,
    batch_size: int = Query(50, ge=1, le=100, description="Batch size (1-100)"),
    db: Session = Depends(get_db_with_rls)
) -> BulkEmbeddingResponse:
    """
    Generate embeddings for memories without one (batch operation).
    Processes up to batch_size memories per call.
    Call repeatedly until processed=0 to embed all memories.
    """
    processed = MemoryOperations.bulk_generate_embeddings(
        session=db,
        anima_id=anima_id,
        batch_size=batch_size
    )

    return BulkEmbeddingResponse(
        status="completed",
        anima_id=anima_id,
        processed=processed
    )
