"""DTOs for Meditation session and action endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.database.meditations import (
    MeditationActionType,
    MeditationPhase,
    MeditationStatus,
    MeditationTriggerType,
)


# ─────────────────────────────────────────────────────────────
# Request DTOs
# ─────────────────────────────────────────────────────────────


class MeditationTriggerRequest(BaseModel):
    """Request to manually trigger a meditation for an Anima."""

    anima_id: UUID = Field(description="Anima to trigger meditation for")


# ─────────────────────────────────────────────────────────────
# Response DTOs
# ─────────────────────────────────────────────────────────────


class MeditationSessionRead(BaseModel):
    """Response model for meditation session data."""

    id: UUID
    anima_id: UUID
    trigger_type: MeditationTriggerType
    triggered_by: UUID | None = None

    started_at: datetime
    completed_at: datetime | None = None

    status: MeditationStatus
    error_message: str | None = None

    knowledge_reviewed: int = 0
    knowledge_modified: int = 0
    knowledge_created: int = 0
    knowledge_deleted: int = 0

    summary: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MeditationActionRead(BaseModel):
    """Response model for individual meditation action."""

    id: UUID
    session_id: UUID

    action_type: MeditationActionType
    phase: MeditationPhase

    source_knowledge_ids: list[UUID]
    result_knowledge_ids: list[UUID] | None = None

    before_state: dict[str, Any]
    after_state: dict[str, Any] | None = None

    reasoning: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MeditationSessionWithActions(MeditationSessionRead):
    """Meditation session with all its actions included."""

    actions: list[MeditationActionRead] = Field(default_factory=list)
