"""Animas API endpoints.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.database import get_db
from app.domain.anima_operations import AnimaOperations
from app.models.database.animas import AnimaCreate, AnimaRead, AnimaUpdate


router = APIRouter(prefix="/animas", tags=["animas"])


@router.post(
    "",
    response_model=AnimaRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create anima"
)
async def create_anima(
    data: AnimaCreate,
    db: Session = Depends(get_db)
) -> AnimaRead:
    """Create new anima. Name required, description and meta optional."""
    anima = AnimaOperations.create(db, data)  # No await!
    return AnimaRead.model_validate(anima)


@router.get(
    "/search",
    response_model=List[AnimaRead],
    summary="Search animas by name"
)
async def search_animas(
    name: str = Query(..., description="Name query (partial match, case-insensitive)", min_length=1),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    db: Session = Depends(get_db)
) -> List[AnimaRead]:
    """Search animas by name using partial matching (ILIKE). Ordered alphabetically."""
    animas = AnimaOperations.search_by_name(db, name, limit)  # No await!
    return [AnimaRead.model_validate(anima) for anima in animas]


@router.get(
    "",
    response_model=List[AnimaRead],
    summary="List animas"
)
async def list_animas(
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db)
) -> List[AnimaRead]:
    """List all animas, paginated, ordered DESC (newest first)."""
    animas = AnimaOperations.get_all(db, limit, offset, include_deleted)  # No await!
    return [AnimaRead.model_validate(anima) for anima in animas]


@router.get(
    "/{anima_id}/with-events",
    response_model=AnimaRead,
    summary="Get anima with events"
)
async def get_anima_with_events(
    anima_id: UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db)
) -> AnimaRead:
    """Get anima with eager-loaded events relationship. Avoids N+1 queries."""
    anima = AnimaOperations.get_with_events(db, anima_id, include_deleted)  # No await!
    if not anima:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anima {anima_id} not found"
        )

    return AnimaRead.model_validate(anima)


@router.get(
    "/{anima_id}",
    response_model=AnimaRead,
    summary="Get anima by ID"
)
async def get_anima(
    anima_id: UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db)
) -> AnimaRead:
    """Get specific anima by UUID."""
    anima = AnimaOperations.get_by_id(db, anima_id, include_deleted)  # No await!
    if not anima:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anima {anima_id} not found"
        )

    return AnimaRead.model_validate(anima)


@router.patch(
    "/{anima_id}",
    response_model=AnimaRead,
    summary="Update anima"
)
async def update_anima(
    anima_id: UUID,
    data: AnimaUpdate,
    db: Session = Depends(get_db)
) -> AnimaRead:
    """Update anima (partial). Can update name, description, meta, is_deleted."""
    try:
        anima = AnimaOperations.update(db, anima_id, data)  # No await!
        return AnimaRead.model_validate(anima)
    except HTTPException:
        raise


@router.post(
    "/{anima_id}/restore",
    response_model=AnimaRead,
    summary="Restore soft-deleted anima"
)
async def restore_anima(
    anima_id: UUID,
    db: Session = Depends(get_db)
) -> AnimaRead:
    """Restore soft-deleted anima (undelete)."""
    try:
        anima = AnimaOperations.restore(db, anima_id)  # No await!
        return AnimaRead.model_validate(anima)
    except HTTPException:
        raise


@router.delete(
    "/{anima_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete anima"
)
async def delete_anima(
    anima_id: UUID,
    db: Session = Depends(get_db)
) -> None:
    """Soft delete anima (mark as deleted, preserve for provenance)."""
    try:
        AnimaOperations.soft_delete(db, anima_id)  # No await!
    except HTTPException:
        raise
