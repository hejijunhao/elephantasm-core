"""Meditation session and action models for the Meditator service.

The Meditator curates an Anima's knowledge through periodic "meditation" cycles,
mirroring the Dreamer's memory curation. Each session records all actions taken
(merges, splits, updates, reclassifications, deletes) with before/after snapshots
for full audit trail.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, Relationship, SQLModel

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.animas import Anima
    from app.models.database.user import User


class MeditationTriggerType(str, Enum):
    """How the meditation was initiated."""
    AUTO = "AUTO"      # Count threshold reached (after Nth knowledge synthesis)
    MANUAL = "MANUAL"  # User-triggered via API


class MeditationStatus(str, Enum):
    """Current state of the meditation session."""
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeditationActionType(str, Enum):
    """Type of action performed on knowledge."""
    MERGE = "MERGE"            # Combined multiple knowledge items into one
    SPLIT = "SPLIT"            # Divided one knowledge item into multiple
    UPDATE = "UPDATE"          # Modified knowledge fields (content, confidence, etc.)
    RECLASSIFY = "RECLASSIFY"  # Changed knowledge_type or topic without altering content
    DELETE = "DELETE"           # Soft-deleted as noise or superseded


class MeditationPhase(str, Enum):
    """Which phase of the meditation produced this action."""
    REFLECTION = "REFLECTION"        # Algorithmic (clustering + flagging only)
    CONTEMPLATION = "CONTEMPLATION"  # LLM-powered (merge, split, curation)


class MeditationSession(TimestampMixin, SQLModel, table=True):
    """
    Top-level record of a meditation cycle.

    Tracks timing, metrics, and overall outcome of knowledge curation.
    """
    __tablename__ = "meditation_sessions"
    __table_args__ = (
        Index("ix_meditation_sessions_started_at", text("started_at DESC")),
    )

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    anima_id: UUID = Field(
        sa_column=Column(ForeignKey("animas.id", ondelete="CASCADE"), nullable=False, index=True),
        description="Anima being meditated for",
    )

    # Trigger metadata
    trigger_type: MeditationTriggerType = Field(
        description="How the meditation was initiated (AUTO or MANUAL)"
    )
    triggered_by: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        description="User who triggered (NULL for auto)",
    )

    # Timing
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When meditation execution began"
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When meditation finished (success or failure)"
    )

    # Status
    status: MeditationStatus = Field(
        default=MeditationStatus.RUNNING,
        index=True,
        description="Current state of the meditation"
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if FAILED"
    )

    # Metrics (Knowledge-specific — no "archived" since Knowledge has no state lifecycle)
    knowledge_reviewed: int = Field(
        default=0,
        description="Total knowledge items examined"
    )
    knowledge_modified: int = Field(
        default=0,
        description="Knowledge items updated (includes merge sources)"
    )
    knowledge_created: int = Field(
        default=0,
        description="New knowledge items from merges/splits"
    )
    knowledge_deleted: int = Field(
        default=0,
        description="Knowledge items soft-deleted as noise"
    )

    # LLM-generated summary
    summary: str | None = Field(
        default=None,
        description="Human-readable summary of what happened"
    )

    # Frozen config at meditation time
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'")),
        description="MeditatorConfig values at execution time"
    )

    # Relationships
    actions: list["MeditationAction"] = Relationship(back_populates="session")
    anima: Optional["Anima"] = Relationship()
    triggered_by_user: Optional["User"] = Relationship()


class MeditationAction(SQLModel, table=True):
    """
    Individual action taken during a meditation session.

    Each action records before/after snapshots for audit trail.
    """
    __tablename__ = "meditation_actions"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("meditation_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        ),
        description="Parent meditation session"
    )

    # Action metadata
    action_type: MeditationActionType = Field(
        index=True,
        description="Type of action (MERGE, SPLIT, UPDATE, RECLASSIFY, DELETE)"
    )
    phase: MeditationPhase = Field(
        description="Which phase produced this action"
    )

    # Affected knowledge (stored as UUID arrays)
    source_knowledge_ids: list[UUID] = Field(
        sa_column=Column(ARRAY(PGUUID), nullable=False),
        description="Original knowledge IDs before action"
    )
    result_knowledge_ids: list[UUID] | None = Field(
        default=None,
        sa_column=Column(ARRAY(PGUUID), nullable=True),
        description="Resulting knowledge IDs after action (NULL for DELETE)"
    )

    # Snapshots for audit
    before_state: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
        description="Snapshot of source knowledge before change"
    )
    after_state: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="Snapshot of result knowledge after change (NULL for DELETE)"
    )

    # LLM reasoning (NULL for algorithmic Reflection actions)
    reasoning: str | None = Field(
        default=None,
        description="LLM explanation for this action"
    )

    # Timestamp (immutable - no updated_at)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="When this action was recorded"
    )

    # Relationships
    session: Optional[MeditationSession] = Relationship(back_populates="actions")
