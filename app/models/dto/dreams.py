"""DTOs for Dream session and action endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.database.dreams import (
    DreamActionType,
    DreamPhase,
    DreamStatus,
    DreamTriggerType,
)


# ─────────────────────────────────────────────────────────────
# Request DTOs
# ─────────────────────────────────────────────────────────────


class DreamTriggerRequest(BaseModel):
    """Request to manually trigger a dream for an Anima."""

    anima_id: UUID = Field(description="Anima to trigger dream for")


# ─────────────────────────────────────────────────────────────
# Response DTOs
# ─────────────────────────────────────────────────────────────


class DreamSessionRead(BaseModel):
    """Response model for dream session data."""

    id: UUID
    anima_id: UUID
    trigger_type: DreamTriggerType
    triggered_by: UUID | None = None

    started_at: datetime
    completed_at: datetime | None = None

    status: DreamStatus
    error_message: str | None = None

    memories_reviewed: int = 0
    memories_modified: int = 0
    memories_created: int = 0
    memories_archived: int = 0
    memories_deleted: int = 0

    summary: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DreamActionRead(BaseModel):
    """Response model for individual dream action."""

    id: UUID
    session_id: UUID

    action_type: DreamActionType
    phase: DreamPhase

    source_memory_ids: list[UUID]
    result_memory_ids: list[UUID] | None = None

    before_state: dict[str, Any]
    after_state: dict[str, Any] | None = None

    reasoning: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DreamSessionWithActions(DreamSessionRead):
    """Dream session with all its actions included."""

    actions: list[DreamActionRead] = Field(default_factory=list)
