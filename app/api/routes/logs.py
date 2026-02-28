"""Logs API endpoints - unified activity timeline.

Aggregates events, memories, dreams, knowledge, and audit trails
into a single chronological feed per Anima.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.log_operations import LogOperations
from app.models.dto.log_entry import LogsResponse, LogStats


router = APIRouter(prefix="/logs", tags=["logs"])


@router.get(
    "",
    response_model=LogsResponse,
    summary="List unified activity logs",
)
async def list_logs(
    anima_id: UUID = Query(..., description="Anima UUID to fetch logs for"),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    entity_types: Optional[list[str]] = Query(None, description="Filter by entity types"),
    since: Optional[datetime] = Query(None, description="Start of date range (ISO 8601)"),
    until: Optional[datetime] = Query(None, description="End of date range (ISO 8601)"),
    db: Session = Depends(get_db_with_rls),
) -> LogsResponse:
    """
    Unified chronological activity log for an Anima.

    Merges entries from events, memories, dream sessions, dream actions,
    memory packs, knowledge, identity audit, and knowledge audit tables.
    Sorted by timestamp DESC. RLS enforced via session context.
    """
    return LogOperations.get_logs(
        session=db,
        anima_id=anima_id,
        limit=limit,
        offset=offset,
        entity_types=entity_types,
        since=since,
        until=until,
    )


@router.get(
    "/stats",
    response_model=LogStats,
    summary="Get log entry counts by type",
)
async def get_log_stats(
    anima_id: UUID = Query(..., description="Anima UUID to get stats for"),
    since: Optional[datetime] = Query(None, description="Start of date range (ISO 8601)"),
    until: Optional[datetime] = Query(None, description="End of date range (ISO 8601)"),
    db: Session = Depends(get_db_with_rls),
) -> LogStats:
    """Count of log entries per entity type for an Anima. RLS enforced."""
    return LogOperations.get_stats(
        session=db,
        anima_id=anima_id,
        since=since,
        until=until,
    )
