"""API routes for Identity entity."""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain.identity_operations import IdentityOperations
from app.domain.identity_audit_operations import IdentityAuditOperations
from app.models.database.identity import (
    IdentityCreate,
    IdentityUpdate,
    IdentityRead,
    IdentityAssessment,
)
from app.models.database.identity_audit_log import (
    IdentityAuditAction,
    IdentityAuditLogCreate,
    IdentityAuditLogRead,
)

router = APIRouter(prefix="/identities", tags=["identities"])

# --- Identity CRUD ---


@router.post("", response_model=IdentityRead, status_code=status.HTTP_201_CREATED)
async def create_identity(
    anima_id: UUID = Query(..., description="Anima ID (required)"),
    data: IdentityCreate = None,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """
    Create Identity for an Anima.

    Each Anima can only have one Identity (1:1 relationship).
    Automatically creates audit log entry with action=CREATE.
    """
    # Check if Identity already exists for this Anima
    if IdentityOperations.exists_for_anima(db, anima_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Identity already exists for Anima {anima_id}"
        )

    # Default to empty IdentityCreate if not provided
    if data is None:
        data = IdentityCreate()

    identity = IdentityOperations.create(db, anima_id, data)

    # Create audit log entry
    audit_data = IdentityAuditLogCreate(
        identity_id=identity.id,
        action=IdentityAuditAction.CREATE,
        trigger_source="api_create",
        after_state=identity.model_dump(mode="json")
    )
    IdentityAuditOperations.create(db, audit_data)

    return IdentityRead.model_validate(identity)


@router.get("/anima/{anima_id}", response_model=IdentityRead)
async def get_identity_by_anima(
    anima_id: UUID,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """Get Identity by Anima ID."""
    identity = IdentityOperations.get_by_anima_id(db, anima_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity not found for Anima {anima_id}"
        )
    return IdentityRead.model_validate(identity)


@router.get("/{identity_id}", response_model=IdentityRead)
async def get_identity(
    identity_id: UUID,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """Get Identity by ID."""
    identity = IdentityOperations.get_by_id(db, identity_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found"
        )
    return IdentityRead.model_validate(identity)


@router.patch("/{identity_id}", response_model=IdentityRead)
async def update_identity(
    identity_id: UUID,
    data: IdentityUpdate,
    source_memory_id: Optional[UUID] = Query(None, description="Source Memory UUID (if memory-triggered)"),
    trigger_source: Optional[str] = Query(None, description="Who/what triggered update"),
    db: Session = Depends(get_db)
) -> IdentityRead:
    """
    Update Identity entry.

    Automatically creates audit log entry with before/after state snapshots.
    """
    # Get before state
    identity_before = IdentityOperations.get_by_id(db, identity_id)
    if not identity_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found"
        )
    before_state = identity_before.model_dump(mode="json")

    # Update
    identity_after = IdentityOperations.update(db, identity_id, data)
    after_state = identity_after.model_dump(mode="json")

    # Create audit log entry
    audit_data = IdentityAuditLogCreate(
        identity_id=identity_id,
        action=IdentityAuditAction.UPDATE,
        trigger_source=trigger_source or "api_update",
        source_memory_id=source_memory_id,
        before_state=before_state,
        after_state=after_state
    )
    IdentityAuditOperations.create(db, audit_data)

    return IdentityRead.model_validate(identity_after)


@router.post("/{identity_id}/assess", response_model=IdentityRead)
async def assess_personality(
    identity_id: UUID,
    assessment: IdentityAssessment,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """
    Submit personality assessment for Identity.

    Updates personality_type, spectrums, confidence, and increments assessment_count.
    Automatically creates audit log entry with action=ASSESS.
    """
    # Get before state
    identity_before = IdentityOperations.get_by_id(db, identity_id)
    if not identity_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found"
        )
    before_state = identity_before.model_dump(mode="json")

    # Apply assessment
    identity_after = IdentityOperations.assess(db, identity_id, assessment)
    after_state = identity_after.model_dump(mode="json")

    # Create audit log entry
    audit_data = IdentityAuditLogCreate(
        identity_id=identity_id,
        action=IdentityAuditAction.ASSESS,
        trigger_source=assessment.trigger_source or "api_assess",
        before_state=before_state,
        after_state=after_state,
        change_summary=f"Personality assessed as {assessment.personality_type} with {assessment.confidence:.0%} confidence"
    )
    IdentityAuditOperations.create(db, audit_data)

    return IdentityRead.model_validate(identity_after)


@router.delete("/{identity_id}", response_model=IdentityRead)
async def delete_identity(
    identity_id: UUID,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """
    Soft delete Identity.

    Automatically creates audit log entry with before/after state.
    """
    # Get before state
    identity_before = IdentityOperations.get_by_id(db, identity_id)
    if not identity_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found"
        )
    before_state = identity_before.model_dump(mode="json")

    # Soft delete
    identity = IdentityOperations.soft_delete(db, identity_id)
    after_state = identity.model_dump(mode="json")

    # Create audit log entry
    audit_data = IdentityAuditLogCreate(
        identity_id=identity_id,
        action=IdentityAuditAction.UPDATE,
        trigger_source="api_delete",
        before_state=before_state,
        after_state=after_state,
        change_summary="Identity soft-deleted"
    )
    IdentityAuditOperations.create(db, audit_data)

    return IdentityRead.model_validate(identity)


@router.post("/{identity_id}/restore", response_model=IdentityRead)
async def restore_identity(
    identity_id: UUID,
    db: Session = Depends(get_db)
) -> IdentityRead:
    """
    Restore soft-deleted Identity.

    Automatically creates audit log entry.
    """
    # Get before state
    identity_before = IdentityOperations.get_by_id(db, identity_id, include_deleted=True)
    if not identity_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {identity_id} not found"
        )
    before_state = identity_before.model_dump(mode="json")

    # Restore
    identity = IdentityOperations.restore(db, identity_id)
    after_state = identity.model_dump(mode="json")

    # Create audit log entry
    audit_data = IdentityAuditLogCreate(
        identity_id=identity_id,
        action=IdentityAuditAction.UPDATE,
        trigger_source="api_restore",
        before_state=before_state,
        after_state=after_state,
        change_summary="Identity restored"
    )
    IdentityAuditOperations.create(db, audit_data)

    return IdentityRead.model_validate(identity)


# --- Evolution / Audit Log ---


@router.get("/{identity_id}/history", response_model=List[IdentityAuditLogRead])
async def get_identity_history(
    identity_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
) -> List[IdentityAuditLogRead]:
    """Get full audit history for an Identity."""
    logs = IdentityAuditOperations.get_by_identity_id(db, identity_id, limit, offset)
    return [IdentityAuditLogRead.model_validate(log) for log in logs]


@router.get("/{identity_id}/evolution", response_model=List[IdentityAuditLogRead])
async def get_identity_evolution(
    identity_id: UUID,
    db: Session = Depends(get_db)
) -> List[IdentityAuditLogRead]:
    """
    Get evolution chain: all changes in chronological order.
    Useful for visualizing personality evolution over time.
    """
    logs = IdentityAuditOperations.get_evolution_chain(db, identity_id)
    return [IdentityAuditLogRead.model_validate(log) for log in logs]


@router.get("/{identity_id}/assessments", response_model=List[IdentityAuditLogRead])
async def get_identity_assessments(
    identity_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
) -> List[IdentityAuditLogRead]:
    """Get all personality assessments for an Identity (ASSESS actions only)."""
    logs = IdentityAuditOperations.get_assessments(db, identity_id, limit)
    return [IdentityAuditLogRead.model_validate(log) for log in logs]


@router.get("/memory/{memory_id}/influenced", response_model=List[UUID])
async def get_identities_influenced_by_memory(
    memory_id: UUID,
    db: Session = Depends(get_db)
) -> List[UUID]:
    """
    Reverse provenance: Get all Identity IDs influenced by a specific Memory.
    Useful for understanding Memory impact on Identity layer.
    """
    return IdentityAuditOperations.get_influenced_identities(db, memory_id)
