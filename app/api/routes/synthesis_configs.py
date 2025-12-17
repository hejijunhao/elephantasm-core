"""Synthesis Config API endpoints.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.synthesis_config_operations import SynthesisConfigOperations
from app.domain.synthesis_metrics import compute_accumulation_score
from app.models.database.synthesis_config import SynthesisConfigRead, SynthesisConfigUpdate, SynthesisStatusResponse


router = APIRouter(tags=["synthesis-config"])


@router.get(
    "/animas/{anima_id}/synthesis-config",
    response_model=SynthesisConfigRead,
    summary="Get synthesis configuration"
)
async def get_synthesis_config(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> SynthesisConfigRead:
    """
    Get synthesis configuration for anima.
    RLS policies automatically filter by authenticated user.

    Auto-creates with defaults if doesn't exist.
    Returns 404 if anima not owned by current user.
    """
    config = SynthesisConfigOperations.get_or_create_default(db, anima_id)
    return SynthesisConfigRead.model_validate(config)


@router.put(
    "/animas/{anima_id}/synthesis-config",
    response_model=SynthesisConfigRead,
    summary="Update synthesis configuration"
)
async def update_synthesis_config(
    anima_id: UUID,
    data: SynthesisConfigUpdate,
    db: Session = Depends(get_db_with_rls)
) -> SynthesisConfigRead:
    """
    Update synthesis configuration for anima.

    Partial update - only provided fields are changed.
    Creates with defaults if doesn't exist.
    """
    try:
        config = SynthesisConfigOperations.update(db, anima_id, data)
        return SynthesisConfigRead.model_validate(config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.delete(
    "/animas/{anima_id}/synthesis-config",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset synthesis configuration"
)
async def reset_synthesis_config(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
):
    """
    Reset synthesis configuration to defaults.

    Deletes custom config; next GET will recreate with env var defaults.
    """
    SynthesisConfigOperations.delete(db, anima_id)
    return None


@router.get(
    "/animas/{anima_id}/synthesis-status",
    response_model=SynthesisStatusResponse,
    summary="Get synthesis status (score vs threshold)"
)
async def get_synthesis_status(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> SynthesisStatusResponse:
    """
    Get current synthesis accumulation status for anima.

    Returns current score, threshold, percentage, and factor breakdown.
    Useful for real-time threshold visualization (progress bars).
    """
    # Get config (includes threshold)
    config = SynthesisConfigOperations.get_or_create_default(db, anima_id)

    # Compute current accumulation score
    metrics = compute_accumulation_score(db, anima_id)

    # Calculate percentage
    percentage = (metrics["accumulation_score"] / config.threshold) * 100 if config.threshold > 0 else 0

    return SynthesisStatusResponse(
        accumulation_score=metrics["accumulation_score"],
        threshold=config.threshold,
        percentage=percentage,
        time_factor=metrics["time_factor"],
        event_factor=metrics["event_factor"],
        token_factor=metrics["token_factor"],
        event_count=metrics["event_count"],
        hours_since_last=metrics["hours_since_last"]
    )
