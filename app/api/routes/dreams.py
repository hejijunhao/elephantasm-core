"""
Dream session and journal API routes.

Endpoints for triggering dreams and viewing dream history (the Dream Journal).
"""

from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlmodel import Session, select

from app.core.auth import require_current_user_id
from app.core.rls_dependencies import get_db_with_rls
from app.api.deps import FeatureGate, RequireActionAllowed, SubscriptionContext
from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import (
    DreamAction,
    DreamSession,
    DreamStatus,
    DreamTriggerType,
)
from app.models.dto.dreams import (
    DreamActionRead,
    DreamSessionRead,
    DreamSessionWithActions,
    DreamTriggerRequest,
)
from app.services.dreamer.dreamer_service import run_dream_background

router = APIRouter(prefix="/dreams", tags=["dreams"])


# ─────────────────────────────────────────────────────────────────
# Manual Trigger
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/trigger",
    response_model=DreamSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_dream(
    request: DreamTriggerRequest,
    background_tasks: BackgroundTasks,
    _feature: bool = Depends(FeatureGate("dreamer_enabled")),
    ctx: SubscriptionContext = Depends(RequireActionAllowed("synthesis")),
    db: Session = Depends(get_db_with_rls),
) -> DreamSessionRead:
    """
    Manually trigger a dream for an Anima.

    Returns 202 Accepted with session ID. Dream runs in background.
    Poll GET /sessions/{id} to check status (RUNNING → COMPLETED/FAILED).

    **Concurrency Guard**: Only one dream per Anima at a time.
    Returns 409 Conflict if a dream is already running.

    **Plan Restrictions**:
    - Requires `dreamer_enabled` feature (Pro, Team, Enterprise only)
    - Subject to monthly synthesis limit based on plan tier
    """
    # Concurrency guard: only one dream per Anima at a time
    if DreamerOperations.has_running_session(db, request.anima_id):
        existing = db.exec(
            select(DreamSession)
            .where(DreamSession.anima_id == request.anima_id)
            .where(DreamSession.status == DreamStatus.RUNNING)
        ).first()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dream already in progress (session: {existing.id if existing else 'unknown'})",
        )

    # Create session immediately (RUNNING status)
    dream_session = DreamerOperations.create_session(
        db,
        anima_id=request.anima_id,
        trigger_type=DreamTriggerType.MANUAL,
        triggered_by=ctx.user_id,
    )
    db.commit()  # Commit so background task can see it

    # Add dream execution to background (non-blocking)
    # Pass user_id for RLS context in background task
    background_tasks.add_task(
        run_dream_background,
        anima_id=request.anima_id,
        session_id=dream_session.id,
        user_id=ctx.user_id,
    )

    return DreamSessionRead.model_validate(dream_session)


# ─────────────────────────────────────────────────────────────────
# Session Management
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/cancel",
    response_model=DreamSessionRead,
)
async def cancel_dream_session(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
    user_id: UUID = Depends(require_current_user_id),
) -> DreamSessionRead:
    """
    Cancel a running dream session.

    Used for manual recovery when a session gets stuck.
    Only RUNNING sessions can be cancelled.

    Returns 400 if session is not RUNNING.
    Returns 404 if session not found (or not owned by user via RLS).
    """
    try:
        dream = DreamerOperations.cancel_session(
            db, session_id, cancelled_by=user_id
        )
        db.commit()
        return DreamSessionRead.model_validate(dream)
    except ValueError as e:
        # Check if it's a "not found" vs "wrong status" error
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ─────────────────────────────────────────────────────────────────
# Session Queries
# ─────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[DreamSessionRead])
async def list_dream_sessions(
    anima_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: DreamStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db_with_rls),
) -> list[DreamSessionRead]:
    """
    List dream sessions for an Anima.

    RLS automatically filters to user's Animas.

    **Filtering**:
    - `status`: Filter by session status (RUNNING, COMPLETED, FAILED)

    **Sorting**: Most recent first (started_at DESC)
    """
    query = (
        select(DreamSession)
        .where(DreamSession.anima_id == anima_id)
        .order_by(DreamSession.started_at.desc())
    )

    if status_filter:
        query = query.where(DreamSession.status == status_filter)

    query = query.offset(offset).limit(limit)
    sessions = db.exec(query).all()

    return [DreamSessionRead.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=DreamSessionRead)
async def get_dream_session(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> DreamSessionRead:
    """
    Get a specific dream session.

    RLS enforced — only accessible if user owns the Anima.
    """
    dream = db.get(DreamSession, session_id)
    if not dream:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dream session not found",
        )
    return DreamSessionRead.model_validate(dream)


@router.get(
    "/sessions/{session_id}/with-actions",
    response_model=DreamSessionWithActions,
)
async def get_dream_session_with_actions(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> DreamSessionWithActions:
    """
    Get a dream session with all its actions included.

    Combines session metadata with the full dream journal (action log).
    """
    dream = db.get(DreamSession, session_id)
    if not dream:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dream session not found",
        )

    # Get actions ordered by creation time
    actions = db.exec(
        select(DreamAction)
        .where(DreamAction.session_id == session_id)
        .order_by(DreamAction.created_at)
    ).all()

    return DreamSessionWithActions(
        **DreamSessionRead.model_validate(dream).model_dump(),
        actions=[DreamActionRead.model_validate(a) for a in actions],
    )


# ─────────────────────────────────────────────────────────────────
# Action Queries (Dream Journal)
# ─────────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/actions",
    response_model=list[DreamActionRead],
)
async def list_dream_actions(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> list[DreamActionRead]:
    """
    List all actions from a dream session (the dream journal).

    Shows every action taken during the dream, ordered by execution time.
    Each action includes:
    - action_type: MERGE, SPLIT, UPDATE, ARCHIVE, DELETE
    - phase: LIGHT_SLEEP (algorithmic) or DEEP_SLEEP (LLM)
    - before_state / after_state: Snapshots for audit/rollback
    - reasoning: LLM explanation (for Deep Sleep actions)
    """
    # Verify session exists (RLS filters to user's Animas)
    dream = db.get(DreamSession, session_id)
    if not dream:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dream session not found",
        )

    actions = db.exec(
        select(DreamAction)
        .where(DreamAction.session_id == session_id)
        .order_by(DreamAction.created_at)
    ).all()

    return [DreamActionRead.model_validate(a) for a in actions]


# ─────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_dream_stats(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """
    Get dream statistics for an Anima.

    Returns:
    - total_dreams: Total number of dream sessions
    - completed_dreams: Successfully completed dreams
    - failed_dreams: Dreams that failed
    - last_dream_at: Timestamp of last completed dream
    - total_memories_modified: Sum of all modifications
    - total_merges: Sum of all merges (memories_created)
    """
    from sqlalchemy import func as sa_func

    # Count sessions by status via SQL
    status_counts = dict(
        db.exec(
            select(DreamSession.status, sa_func.count())
            .where(DreamSession.anima_id == anima_id)
            .group_by(DreamSession.status)
        ).all()
    )
    completed = status_counts.get(DreamStatus.COMPLETED, 0)
    failed = status_counts.get(DreamStatus.FAILED, 0)
    running = status_counts.get(DreamStatus.RUNNING, 0)
    total = sum(status_counts.values())

    # Get last completed dream
    last_dream = DreamerOperations.get_last_session(db, anima_id)

    # Aggregate metrics from completed sessions via SQL
    metrics = db.exec(
        select(
            sa_func.coalesce(sa_func.sum(DreamSession.memories_reviewed), 0),
            sa_func.coalesce(sa_func.sum(DreamSession.memories_modified), 0),
            sa_func.coalesce(sa_func.sum(DreamSession.memories_created), 0),
            sa_func.coalesce(sa_func.sum(DreamSession.memories_archived), 0),
            sa_func.coalesce(sa_func.sum(DreamSession.memories_deleted), 0),
        )
        .where(DreamSession.anima_id == anima_id)
        .where(DreamSession.status == DreamStatus.COMPLETED)
    ).one()
    total_reviewed, total_modified, total_created, total_archived, total_deleted = metrics

    return {
        "anima_id": str(anima_id),
        "total_dreams": total,
        "completed_dreams": completed,
        "failed_dreams": failed,
        "running_dreams": running,
        "last_dream_at": (
            (last_dream.completed_at or last_dream.started_at).isoformat()
            if last_dream else None
        ),
        "aggregate_metrics": {
            "memories_reviewed": total_reviewed,
            "memories_modified": total_modified,
            "memories_created": total_created,
            "memories_archived": total_archived,
            "memories_deleted": total_deleted,
        },
    }
