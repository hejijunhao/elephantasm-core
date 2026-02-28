"""IOConfig API endpoints.

Pattern: Async routes + Sync domain operations.
FastAPI automatically runs sync code in thread pool.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.io_config_operations import IOConfigOperations
from app.models.database.io_config import (
    IOConfigRead,
    IOConfigUpdate,
    IOConfigDefaultsResponse,
)


router = APIRouter(tags=["io-config"])


@router.get(
    "/animas/{anima_id}/io-config",
    response_model=IOConfigRead,
    summary="Get I/O configuration"
)
async def get_io_config(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> IOConfigRead:
    """
    Get I/O configuration for anima.
    RLS policies automatically filter by authenticated user.

    Auto-creates with defaults if doesn't exist.
    Returns 404 if anima not owned by current user.
    """
    try:
        config = IOConfigOperations.get_or_create(db, anima_id)
        return IOConfigRead.model_validate(config)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anima {anima_id} not found or not accessible"
        )


@router.patch(
    "/animas/{anima_id}/io-config",
    response_model=IOConfigRead,
    summary="Update I/O configuration"
)
async def update_io_config(
    anima_id: UUID,
    data: IOConfigUpdate,
    db: Session = Depends(get_db_with_rls)
) -> IOConfigRead:
    """
    Update I/O configuration for anima.

    Partial update - settings are deep merged with existing.
    Creates with defaults if doesn't exist.
    """
    try:
        config = IOConfigOperations.update(db, anima_id, data)
        return IOConfigRead.model_validate(config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.patch(
    "/animas/{anima_id}/io-config/read",
    response_model=IOConfigRead,
    summary="Update read (inbound) settings"
)
async def update_read_settings(
    anima_id: UUID,
    settings: dict[str, Any],
    db: Session = Depends(get_db_with_rls)
) -> IOConfigRead:
    """
    Update read (inbound) settings for anima.

    Deep merges with existing settings.
    Creates with defaults if doesn't exist.
    """
    try:
        config = IOConfigOperations.update_read_settings(db, anima_id, settings)
        return IOConfigRead.model_validate(config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.patch(
    "/animas/{anima_id}/io-config/write",
    response_model=IOConfigRead,
    summary="Update write (outbound) settings"
)
async def update_write_settings(
    anima_id: UUID,
    settings: dict[str, Any],
    db: Session = Depends(get_db_with_rls)
) -> IOConfigRead:
    """
    Update write (outbound) settings for anima.

    Deep merges with existing settings.
    Creates with defaults if doesn't exist.
    """
    try:
        config = IOConfigOperations.update_write_settings(db, anima_id, settings)
        return IOConfigRead.model_validate(config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/animas/{anima_id}/io-config/reset",
    response_model=IOConfigRead,
    summary="Reset I/O configuration to defaults"
)
async def reset_io_config(
    anima_id: UUID,
    db: Session = Depends(get_db_with_rls)
) -> IOConfigRead:
    """
    Reset I/O configuration to default settings.

    Overwrites all settings with system defaults.
    Creates config if doesn't exist.
    """
    try:
        config = IOConfigOperations.reset_to_defaults(db, anima_id)
        return IOConfigRead.model_validate(config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get(
    "/io-config/defaults",
    response_model=IOConfigDefaultsResponse,
    summary="Get default I/O settings"
)
async def get_default_settings() -> IOConfigDefaultsResponse:
    """
    Get default I/O settings for UI reference.

    Does not require authentication.
    Useful for displaying defaults in configuration UI.
    """
    defaults = IOConfigOperations.get_defaults()
    return IOConfigDefaultsResponse(**defaults)
