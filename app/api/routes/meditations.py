"""
Meditation session and journal API routes.

Endpoints for triggering meditations and viewing meditation history.
Mirrors the dreams.py route structure for Knowledge curation.
"""

from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    status,
)
from sqlmodel import Session, select

from app.api.deps import FeatureGate, RequireActionAllowed, SubscriptionContext
from app.core.auth import require_current_user_id
from app.core.rls_dependencies import get_db_with_rls
from app.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from app.domain.meditator_operations import MeditatorOperations
from app.models.database.meditations import (
    MeditationAction,
    MeditationSession,
    MeditationStatus,
    MeditationTriggerType,
)
from app.models.dto.meditations import (
    MeditationActionRead,
    MeditationSessionRead,
    MeditationSessionWithActions,
    MeditationTriggerRequest,
)
from app.services.meditator.meditator_service import run_meditation_background

router = APIRouter(prefix="/meditations", tags=["meditations"])


# ─────────────────────────────────────────────────────────────────
# Manual Trigger
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/trigger",
    response_model=MeditationSessionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_meditation(
    request: MeditationTriggerRequest,
    background_tasks: BackgroundTasks,
    _feature: bool = Depends(FeatureGate("dreamer_enabled")),
    ctx: SubscriptionContext = Depends(RequireActionAllowed("synthesis")),
    db: Session = Depends(get_db_with_rls),
) -> MeditationSessionRead:
    """
    Manually trigger a meditation for an Anima.

    Returns 202 Accepted with session ID. Meditation runs in background.
    Poll GET /sessions/{id} to check status (RUNNING → COMPLETED/FAILED).

    **Concurrency Guard**: Only one meditation per Anima at a time.
    Returns 409 Conflict if a meditation is already running.

    **Plan Restrictions**:
    - Requires `dreamer_enabled` feature (Pro, Team, Enterprise only)
    - Subject to monthly synthesis limit based on plan tier
    """
    # Validate anima exists and belongs to current user (RLS-scoped)
    from app.models.database.animas import Anima

    anima = db.get(Anima, request.anima_id)
    if not anima:
        raise EntityNotFoundError("Anima", request.anima_id)

    if MeditatorOperations.has_running_session(db, request.anima_id):
        raise DuplicateEntityError(
            "Meditation already in progress for this Anima"
        )

    meditation_session = MeditatorOperations.create_session(
        db,
        anima_id=request.anima_id,
        trigger_type=MeditationTriggerType.MANUAL,
        triggered_by=ctx.user_id,
    )
    db.commit()

    background_tasks.add_task(
        run_meditation_background,
        anima_id=request.anima_id,
        session_id=meditation_session.id,
        user_id=ctx.user_id,
    )

    return MeditationSessionRead.model_validate(meditation_session)


# ─────────────────────────────────────────────────────────────────
# Session Management
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/cancel",
    response_model=MeditationSessionRead,
)
async def cancel_meditation_session(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
    user_id: UUID = Depends(require_current_user_id),
) -> MeditationSessionRead:
    """
    Cancel a running meditation session.

    Used for manual recovery when a session gets stuck.
    Only RUNNING sessions can be cancelled.
    """
    meditation = MeditatorOperations.cancel_session(
        db, session_id, cancelled_by=user_id
    )
    db.commit()
    return MeditationSessionRead.model_validate(meditation)


# ─────────────────────────────────────────────────────────────────
# Session Queries
# ─────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[MeditationSessionRead])
async def list_meditation_sessions(
    anima_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: MeditationStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db_with_rls),
) -> list[MeditationSessionRead]:
    """
    List meditation sessions for an Anima.

    RLS automatically filters to user's Animas.
    Most recent first (started_at DESC).
    """
    query = (
        select(MeditationSession)
        .where(MeditationSession.anima_id == anima_id)
        .order_by(MeditationSession.started_at.desc())
    )

    if status_filter is not None:
        query = query.where(MeditationSession.status == status_filter)

    query = query.offset(offset).limit(limit)
    sessions = db.execute(query).scalars().all()

    return [MeditationSessionRead.model_validate(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=MeditationSessionRead)
async def get_meditation_session(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> MeditationSessionRead:
    """Get a specific meditation session."""
    meditation = db.get(MeditationSession, session_id)
    if not meditation:
        raise EntityNotFoundError("MeditationSession", session_id)
    return MeditationSessionRead.model_validate(meditation)


@router.get(
    "/sessions/{session_id}/with-actions",
    response_model=MeditationSessionWithActions,
)
async def get_meditation_session_with_actions(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> MeditationSessionWithActions:
    """Get a meditation session with all its actions included."""
    meditation = db.get(MeditationSession, session_id)
    if not meditation:
        raise EntityNotFoundError("MeditationSession", session_id)

    actions = db.execute(
        select(MeditationAction)
        .where(MeditationAction.session_id == session_id)
        .order_by(MeditationAction.created_at)
    ).scalars().all()

    return MeditationSessionWithActions(
        **MeditationSessionRead.model_validate(meditation).model_dump(),
        actions=[MeditationActionRead.model_validate(a) for a in actions],
    )


# ─────────────────────────────────────────────────────────────────
# Action Queries (Meditation Journal)
# ─────────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/actions",
    response_model=list[MeditationActionRead],
)
async def list_meditation_actions(
    session_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> list[MeditationActionRead]:
    """
    List all actions from a meditation session.

    Each action includes:
    - action_type: MERGE, SPLIT, UPDATE, RECLASSIFY, DELETE
    - phase: REFLECTION (algorithmic) or CONTEMPLATION (LLM)
    - before_state / after_state: Snapshots for audit
    - reasoning: LLM explanation (for Contemplation actions)
    """
    meditation = db.get(MeditationSession, session_id)
    if not meditation:
        raise EntityNotFoundError("MeditationSession", session_id)

    actions = db.execute(
        select(MeditationAction)
        .where(MeditationAction.session_id == session_id)
        .order_by(MeditationAction.created_at)
    ).scalars().all()

    return [MeditationActionRead.model_validate(a) for a in actions]


# ─────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_meditation_stats(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls),
) -> dict[str, Any]:
    """
    Get meditation statistics for an Anima.

    Returns session counts, last meditation timestamp,
    and aggregate knowledge modification metrics.
    """
    from sqlalchemy import func as sa_func

    # Count sessions by status
    status_counts = dict(
        db.execute(
            select(MeditationSession.status, sa_func.count())
            .where(MeditationSession.anima_id == anima_id)
            .group_by(MeditationSession.status)
        ).all()
    )
    completed = status_counts.get(MeditationStatus.COMPLETED, 0)
    failed = status_counts.get(MeditationStatus.FAILED, 0)
    running = status_counts.get(MeditationStatus.RUNNING, 0)
    total = sum(status_counts.values())

    # Last completed meditation
    last_meditation = MeditatorOperations.get_last_session(db, anima_id)

    # Aggregate metrics from completed sessions
    metrics = db.execute(
        select(
            sa_func.coalesce(sa_func.sum(MeditationSession.knowledge_reviewed), 0),
            sa_func.coalesce(sa_func.sum(MeditationSession.knowledge_modified), 0),
            sa_func.coalesce(sa_func.sum(MeditationSession.knowledge_created), 0),
            sa_func.coalesce(sa_func.sum(MeditationSession.knowledge_deleted), 0),
        )
        .where(MeditationSession.anima_id == anima_id)
        .where(MeditationSession.status == MeditationStatus.COMPLETED)
    ).one()
    total_reviewed, total_modified, total_created, total_deleted = metrics

    # Current counter status
    count, threshold = MeditatorOperations.get_synth_count(db, anima_id)

    return {
        "anima_id": str(anima_id),
        "total_meditations": total,
        "completed_meditations": completed,
        "failed_meditations": failed,
        "running_meditations": running,
        "last_meditation_at": (
            (last_meditation.completed_at or last_meditation.started_at).isoformat()
            if last_meditation
            else None
        ),
        "counter": {
            "knowledge_synth_count": count,
            "meditation_threshold": threshold,
        },
        "aggregate_metrics": {
            "knowledge_reviewed": total_reviewed,
            "knowledge_modified": total_modified,
            "knowledge_created": total_created,
            "knowledge_deleted": total_deleted,
        },
    }
