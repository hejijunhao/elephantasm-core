"""Animas API endpoints.

Pattern: Async routes + Sync domain operations + RLS filtering.
FastAPI automatically runs sync code in thread pool.
RLS policies automatically filter queries by user_id.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.api.deps import RequireActionAllowed, SubscriptionContext
from app.domain.anima_operations import AnimaOperations
from app.models.database.animas import AnimaCreate, AnimaRead, AnimaSummary, AnimaUpdate


router = APIRouter(prefix="/animas", tags=["animas"])


@router.post(
    "",
    response_model=AnimaRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create anima"
)
async def create_anima(
    data: AnimaCreate,
    ctx: SubscriptionContext = Depends(RequireActionAllowed("create_anima")),
    db: Session = Depends(get_db_with_rls)
) -> AnimaRead:
    """
    Create new anima. Name required, description and meta optional.

    ⚠️ Requires authentication. user_id extracted from JWT token.
    RLS policies automatically enforce ownership on create.
    Subject to active anima limit based on plan tier.
    """
    anima = AnimaOperations.create(db, data, user_id=ctx.user_id, organization_id=ctx.org_id)
    return AnimaRead.model_validate(anima)


@router.get(
    "/search",
    response_model=List[AnimaRead],
    summary="Search animas by name"
)
async def search_animas(
    name: str = Query(..., description="Name query (partial match, case-insensitive)", min_length=1),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    db: Session = Depends(get_db_with_rls)
) -> List[AnimaRead]:
    """Search animas by name using partial matching (ILIKE). RLS filters by user automatically."""
    animas = AnimaOperations.search_by_name(db, name, limit)
    return [AnimaRead.model_validate(anima) for anima in animas]


@router.get(
    "/summary",
    response_model=List[AnimaSummary],
    summary="Get animas with inline stats"
)
async def get_animas_summary(
    db: Session = Depends(get_db_with_rls),
    x_organization_id: str | None = Header(None, alias="X-Organization-Id"),
) -> List[AnimaSummary]:
    """
    All animas for current org with event/memory/knowledge counts.

    Used by the Anima Library card grid. Scalar subqueries avoid cross-join explosion.
    RLS auto-filters by user; org filter is additive for query plan clarity.
    """
    org_id = UUID(x_organization_id) if x_organization_id else None
    return AnimaOperations.get_summary(db, organization_id=org_id)


@router.get(
    "",
    response_model=List[AnimaRead],
    summary="List animas"
)
async def list_animas(
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db_with_rls)
) -> List[AnimaRead]:
    """
    List all animas, paginated, ordered DESC (newest first).

    RLS policies automatically filter by authenticated user.
    Returns only animas owned by current user.
    """
    animas = AnimaOperations.get_all(db, limit, offset, include_deleted)
    return [AnimaRead.model_validate(anima) for anima in animas]


@router.get(
    "/{anima_id}/with-events",
    response_model=AnimaRead,
    summary="Get anima with events"
)
async def get_anima_with_events(
    anima_id: UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db_with_rls)
) -> AnimaRead:
    """
    Get anima with eager-loaded events relationship. Avoids N+1 queries.

    RLS ensures only owned animas are returned (404 if not owned).
    """
    anima = AnimaOperations.get_with_events(db, anima_id, include_deleted)
    if not anima:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anima {anima_id} not found"
        )

    return AnimaRead.model_validate(anima)


@router.get(
    "/{anima_id}/stats",
    response_model=dict,
    summary="Get anima child record counts"
)
async def get_anima_stats(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> dict:
    """
    Get counts of child records (events, memories, knowledge, etc.) for pre-delete summary.

    RLS ensures only owned animas are accessible (404 if not owned).
    """
    return AnimaOperations.get_child_counts(db, anima_id)


@router.get(
    "/{anima_id}",
    response_model=AnimaRead,
    summary="Get anima by ID"
)
async def get_anima(
    anima_id: UUID,
    include_deleted: bool = Query(False, description="Include soft-deleted animas"),
    db: Session = Depends(get_db_with_rls)
) -> AnimaRead:
    """
    Get specific anima by UUID.

    RLS ensures only owned animas are returned (404 if not owned).
    """
    anima = AnimaOperations.get_by_id(db, anima_id, include_deleted)
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
    db: Session = Depends(get_db_with_rls)
) -> AnimaRead:
    """
    Update anima (partial). Can update name, description, meta, is_deleted.

    RLS ensures only owned animas can be updated (404 if not owned).
    """
    anima = AnimaOperations.update(db, anima_id, data)
    return AnimaRead.model_validate(anima)


@router.post(
    "/{anima_id}/restore",
    response_model=dict,
    summary="Restore soft-deleted anima and all child data"
)
async def restore_anima(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> dict:
    """
    Cascade restore anima + all child data. Returns counts of restored records.

    RLS ensures only owned animas can be restored (404 if not owned).
    """
    return AnimaOperations.cascade_restore(db, anima_id)


@router.delete(
    "/{anima_id}",
    response_model=dict,
    summary="Cascade soft-delete anima and all child data"
)
async def delete_anima(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> dict:
    """
    Cascade soft-delete anima + all child data. Returns counts of affected records.

    RLS ensures only owned animas can be deleted (404 if not owned).
    """
    return AnimaOperations.cascade_soft_delete(db, anima_id)
