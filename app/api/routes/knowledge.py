from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.knowledge_operations import KnowledgeOperations
from app.domain.knowledge_audit_operations import KnowledgeAuditOperations
from app.models.database.knowledge import (
    KnowledgeType,
    AuditAction,
    KnowledgeCreate,
    KnowledgeUpdate,
    KnowledgeRead,
)
from app.models.database.knowledge_audit_log import (
    AuditLogCreate,
    AuditLogRead,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ═══════════════════════════════════════════════════════════════════
# Semantic Search Models
# ═══════════════════════════════════════════════════════════════════

class KnowledgeSemanticSearchRequest(BaseModel):
    """Request model for semantic search."""
    anima_id: UUID
    query: str
    limit: int = 10
    threshold: float = 0.7
    knowledge_type: Optional[KnowledgeType] = None


class KnowledgeWithScore(BaseModel):
    """Knowledge with similarity score."""
    knowledge: KnowledgeRead
    score: float


class KnowledgeBulkEmbeddingResponse(BaseModel):
    """Response for bulk embedding generation."""
    status: str
    anima_id: UUID
    processed: int

# --- Knowledge CRUD ---

@router.post("", response_model=KnowledgeRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    data: KnowledgeCreate,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """
    Create new Knowledge entry.

    Automatically creates audit log entry with action=CREATE.
    """
    knowledge = KnowledgeOperations.create(db, data)

    # Create audit log entry
    audit_data = AuditLogCreate(
        knowledge_id=knowledge.id,
        action=AuditAction.CREATE,
        source_type=data.source_type,
        after_state=knowledge.model_dump(mode="json"),
        triggered_by="api_create"
    )
    KnowledgeAuditOperations.create(db, audit_data)

    return KnowledgeRead.model_validate(knowledge)

@router.get("", response_model=List[KnowledgeRead])
async def list_knowledge(
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db_with_rls)
) -> List[KnowledgeRead]:
    """List all Knowledge for an Anima (paginated)."""
    knowledge_list = KnowledgeOperations.get_all(
        db, anima_id, limit, offset, include_deleted
    )
    return [KnowledgeRead.model_validate(k) for k in knowledge_list]

@router.get("/type/{knowledge_type}", response_model=List[KnowledgeRead])
async def list_by_type(
    knowledge_type: KnowledgeType,
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db_with_rls)
) -> List[KnowledgeRead]:
    """Filter Knowledge by type (Fact/Concept/Method/Principle/Experience)."""
    knowledge_list = KnowledgeOperations.filter_by_type(
        db, anima_id, knowledge_type, limit, offset, include_deleted
    )
    return [KnowledgeRead.model_validate(k) for k in knowledge_list]

@router.get("/topic/{topic}", response_model=List[KnowledgeRead])
async def list_by_topic(
    topic: str,
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db_with_rls)
) -> List[KnowledgeRead]:
    """Filter Knowledge by topic (LLM-controlled grouping)."""
    knowledge_list = KnowledgeOperations.filter_by_topic(
        db, anima_id, topic, limit, offset, include_deleted
    )
    return [KnowledgeRead.model_validate(k) for k in knowledge_list]

@router.get("/search", response_model=List[KnowledgeRead])
async def search_knowledge(
    q: str = Query(..., min_length=1, description="Search query"),
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    limit: int = Query(50, ge=1, le=200),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db_with_rls)
) -> List[KnowledgeRead]:
    """Search Knowledge content (case-insensitive)."""
    knowledge_list = KnowledgeOperations.search_content(
        db, anima_id, q, limit, include_deleted
    )
    return [KnowledgeRead.model_validate(k) for k in knowledge_list]

@router.get("/stats")
async def get_knowledge_stats(
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    db: Session = Depends(get_db_with_rls)
) -> dict:
    """Get Knowledge statistics for an Anima."""
    return KnowledgeOperations.get_stats(db, anima_id)

@router.get("/topics")
async def get_unique_topics(
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db_with_rls)
) -> List[str]:
    """Get list of unique topics for an Anima."""
    return KnowledgeOperations.get_unique_topics(db, anima_id, include_deleted)

@router.get("/{knowledge_id}", response_model=KnowledgeRead)
async def get_knowledge(
    knowledge_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """Get Knowledge by ID."""
    knowledge = KnowledgeOperations.get_by_id(db, knowledge_id)
    if not knowledge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge {knowledge_id} not found"
        )
    return KnowledgeRead.model_validate(knowledge)

@router.patch("/{knowledge_id}", response_model=KnowledgeRead)
async def update_knowledge(
    knowledge_id: UUID,
    data: KnowledgeUpdate,
    source_id: Optional[UUID] = Query(None, description="Source Memory UUID (if memory-triggered)"),
    triggered_by: Optional[str] = Query(None, description="Who/what triggered update"),
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """
    Update Knowledge entry.

    Automatically creates audit log entry with before/after state snapshots.
    """
    # Get before state
    knowledge_before = KnowledgeOperations.get_by_id(db, knowledge_id)
    if not knowledge_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge {knowledge_id} not found"
        )
    before_state = knowledge_before.model_dump(mode="json")

    # Update
    knowledge_after = KnowledgeOperations.update(db, knowledge_id, data)
    after_state = knowledge_after.model_dump(mode="json")

    # Create audit log entry
    audit_data = AuditLogCreate(
        knowledge_id=knowledge_id,
        action=AuditAction.UPDATE,
        source_type=knowledge_after.source_type,
        source_id=source_id,
        before_state=before_state,
        after_state=after_state,
        triggered_by=triggered_by or "api_update"
    )
    KnowledgeAuditOperations.create(db, audit_data)

    return KnowledgeRead.model_validate(knowledge_after)

@router.delete("/{knowledge_id}", response_model=KnowledgeRead)
async def delete_knowledge(
    knowledge_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """
    Soft delete Knowledge.

    Automatically creates audit log entry with action=DELETE.
    """
    # Get before state
    knowledge_before = KnowledgeOperations.get_by_id(db, knowledge_id)
    if not knowledge_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge {knowledge_id} not found"
        )
    before_state = knowledge_before.model_dump(mode="json")

    # Soft delete
    knowledge = KnowledgeOperations.soft_delete(db, knowledge_id)
    after_state = knowledge.model_dump(mode="json")

    # Create audit log entry
    audit_data = AuditLogCreate(
        knowledge_id=knowledge_id,
        action=AuditAction.DELETE,
        before_state=before_state,
        after_state=after_state,
        triggered_by="api_delete"
    )
    KnowledgeAuditOperations.create(db, audit_data)

    return KnowledgeRead.model_validate(knowledge)

@router.post("/{knowledge_id}/restore", response_model=KnowledgeRead)
async def restore_knowledge(
    knowledge_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """
    Restore soft-deleted Knowledge.

    Automatically creates audit log entry with action=RESTORE.
    """
    # Get before state
    knowledge_before = KnowledgeOperations.get_by_id(db, knowledge_id, include_deleted=True)
    if not knowledge_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge {knowledge_id} not found"
        )
    before_state = knowledge_before.model_dump(mode="json")

    # Restore
    knowledge = KnowledgeOperations.restore(db, knowledge_id)
    after_state = knowledge.model_dump(mode="json")

    # Create audit log entry
    audit_data = AuditLogCreate(
        knowledge_id=knowledge_id,
        action=AuditAction.RESTORE,
        before_state=before_state,
        after_state=after_state,
        triggered_by="api_restore"
    )
    KnowledgeAuditOperations.create(db, audit_data)

    return KnowledgeRead.model_validate(knowledge)

# --- Provenance / Audit Log ---

@router.get("/{knowledge_id}/history", response_model=List[AuditLogRead])
async def get_knowledge_history(
    knowledge_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_with_rls)
) -> List[AuditLogRead]:
    """Get full audit history for a Knowledge entry."""
    logs = KnowledgeAuditOperations.get_by_knowledge_id(db, knowledge_id, limit, offset)
    return [AuditLogRead.model_validate(log) for log in logs]

@router.get("/{knowledge_id}/provenance", response_model=List[AuditLogRead])
async def get_knowledge_provenance(
    knowledge_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> List[AuditLogRead]:
    """
    Get provenance chain: all source Memories that contributed to this Knowledge.
    Returns audit logs with source_id (Memory UUID) in chronological order.
    """
    logs = KnowledgeAuditOperations.get_provenance_chain(db, knowledge_id)
    return [AuditLogRead.model_validate(log) for log in logs]

@router.get("/memory/{memory_id}/influenced", response_model=List[UUID])
async def get_knowledge_influenced_by_memory(
    memory_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> List[UUID]:
    """
    Reverse provenance: Get all Knowledge IDs that were created/influenced by a specific Memory.
    Useful for understanding Memory impact on Knowledge layer.
    """
    return KnowledgeAuditOperations.get_influenced_knowledge(db, memory_id)


# ═══════════════════════════════════════════════════════════════════
# Semantic Search Endpoints (pgVector)
# ═══════════════════════════════════════════════════════════════════

@router.post("/search/semantic", response_model=List[KnowledgeWithScore])
async def semantic_search_knowledge(
    request: KnowledgeSemanticSearchRequest,
    db: Session = Depends(get_db_with_rls)
) -> List[KnowledgeWithScore]:
    """
    Search knowledge by semantic similarity using vector embeddings.
    Converts query text to embedding, then finds similar knowledge using cosine similarity.
    Requires knowledge to have embeddings generated (via synthesis or bulk generation).
    """
    from app.services.embeddings import get_embedding_provider

    # Generate embedding for query
    provider = get_embedding_provider()
    query_embedding = provider.embed_text(request.query)

    # Search for similar knowledge
    results = KnowledgeOperations.search_similar(
        session=db,
        anima_id=request.anima_id,
        query_embedding=query_embedding,
        limit=request.limit,
        threshold=request.threshold,
        knowledge_type=request.knowledge_type
    )

    return [
        KnowledgeWithScore(knowledge=KnowledgeRead.model_validate(k), score=score)
        for k, score in results
    ]


@router.post("/{knowledge_id}/embedding", response_model=KnowledgeRead)
async def generate_knowledge_embedding(
    knowledge_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeRead:
    """
    Generate embedding for a single knowledge entry.
    Uses OpenAI text-embedding-3-small (1536 dimensions).
    Overwrites existing embedding if present.
    """
    try:
        knowledge = KnowledgeOperations.generate_embedding(db, knowledge_id)
        return KnowledgeRead.model_validate(knowledge)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/embeddings/bulk", response_model=KnowledgeBulkEmbeddingResponse)
async def bulk_generate_knowledge_embeddings(
    anima_id: UUID,
    batch_size: int = Query(50, ge=1, le=100, description="Batch size (1-100)"),
    db: Session = Depends(get_db_with_rls)
) -> KnowledgeBulkEmbeddingResponse:
    """
    Generate embeddings for knowledge entries without one (batch operation).
    """
    processed = KnowledgeOperations.bulk_generate_embeddings(
        session=db,
        anima_id=anima_id,
        batch_size=batch_size
    )

    return KnowledgeBulkEmbeddingResponse(
        status="completed",
        anima_id=anima_id,
        processed=processed
    )
