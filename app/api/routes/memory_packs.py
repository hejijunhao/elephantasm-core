"""Memory Packs API endpoints.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.memory_pack_operations import MemoryPackOperations
from app.models.database.memory_pack import MemoryPackRead, MemoryPackStats


router = APIRouter(tags=["memory-packs"])


@router.get(
    "/animas/{anima_id}/memory-packs",
    response_model=list[MemoryPackRead],
    summary="List memory packs for anima"
)
async def list_memory_packs(
    anima_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_with_rls)
) -> list[MemoryPackRead]:
    """
    List memory packs for anima, newest first.
    RLS policies automatically filter by authenticated user.
    """
    packs = MemoryPackOperations.get_by_anima(db, anima_id, limit, offset)
    return [MemoryPackRead.model_validate(p) for p in packs]


@router.get(
    "/animas/{anima_id}/memory-packs/latest",
    response_model=Optional[MemoryPackRead],
    summary="Get latest memory pack"
)
async def get_latest_memory_pack(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> Optional[MemoryPackRead]:
    """
    Get most recent memory pack for anima.
    Returns null if no packs exist.
    """
    pack = MemoryPackOperations.get_latest(db, anima_id)
    if not pack:
        return None
    return MemoryPackRead.model_validate(pack)


@router.get(
    "/animas/{anima_id}/memory-packs/stats",
    response_model=MemoryPackStats,
    summary="Get memory pack statistics"
)
async def get_memory_pack_stats(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> MemoryPackStats:
    """
    Get aggregated statistics for memory packs.
    Includes averages and usage rates.
    """
    return MemoryPackOperations.get_stats(db, anima_id)


@router.get(
    "/memory-packs/{pack_id}",
    response_model=MemoryPackRead,
    summary="Get memory pack by ID"
)
async def get_memory_pack(
    pack_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> MemoryPackRead:
    """
    Get a specific memory pack by ID.
    Returns 404 if not found or not accessible.
    """
    pack = MemoryPackOperations.get_by_id(db, pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory pack {pack_id} not found"
        )
    return MemoryPackRead.model_validate(pack)


@router.delete(
    "/memory-packs/{pack_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete memory pack"
)
async def delete_memory_pack(
    pack_id: UUID,
    db: Session = Depends(get_db_with_rls)
):
    """
    Delete a specific memory pack.
    Hard delete (packs are ephemeral by nature).
    """
    deleted = MemoryPackOperations.delete_by_id(db, pack_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory pack {pack_id} not found"
        )
    return None
