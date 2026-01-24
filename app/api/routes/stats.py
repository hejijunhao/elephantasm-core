"""Stats API endpoints for settings/usage page.

Pattern: Async routes + Sync domain operations + RLS filtering.
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session
from pydantic import BaseModel

from app.core.rls_dependencies import get_db_with_rls
from app.domain.stats_operations import StatsOperations


router = APIRouter(prefix="/stats", tags=["stats"])


class StatsOverview(BaseModel):
    """Aggregated counts for user's data."""
    animas: int
    events: int
    memories: int
    knowledge: int


@router.get(
    "/overview",
    response_model=StatsOverview,
    summary="Get usage statistics overview"
)
async def get_stats_overview(
    db: Session = Depends(get_db_with_rls)
) -> StatsOverview:
    """
    Get aggregated counts of user's animas, events, memories, and knowledge.

    RLS policies automatically filter by authenticated user.
    Returns only counts for data owned by current user.
    """
    stats = StatsOperations.get_overview(db)
    return StatsOverview(**stats)
