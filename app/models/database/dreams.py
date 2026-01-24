"""Dream session and action models for Elephantasm's Dreamer service.

The Dreamer curates an Anima's memories through periodic "dream" cycles,
analogous to human sleep/dreaming. Each session records all actions taken
(merges, splits, updates, archives, deletes) with before/after snapshots
for full audit trail and potential rollback.
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


class DreamTriggerType(str, Enum):
    """How the dream was initiated."""
    SCHEDULED = "SCHEDULED"  # Periodic scheduler (e.g., every 12h)
    MANUAL = "MANUAL"        # User-triggered via API


class DreamStatus(str, Enum):
    """Current state of the dream session."""
    RUNNING = "RUNNING"      # In progress
    COMPLETED = "COMPLETED"  # Successfully finished
    FAILED = "FAILED"        # Error occurred


class DreamActionType(str, Enum):
    """Type of action performed on memories."""
    MERGE = "MERGE"      # Combined multiple memories into one
    SPLIT = "SPLIT"      # Divided one memory into multiple
    UPDATE = "UPDATE"    # Modified memory fields (summary, scores, etc.)
    ARCHIVE = "ARCHIVE"  # Transitioned to DECAYING or ARCHIVED state
    DELETE = "DELETE"    # Soft-deleted as noise


class DreamPhase(str, Enum):
    """Which phase of the dream produced this action."""
    LIGHT_SLEEP = "LIGHT_SLEEP"  # Algorithmic (decay, transitions, flagging)
    DEEP_SLEEP = "DEEP_SLEEP"    # LLM-powered (merge, split, curation)


class DreamSession(TimestampMixin, SQLModel, table=True):
    """
    Top-level record of a dream cycle.

    Tracks timing, metrics, and overall outcome of memory curation.
    """
    __tablename__ = "dream_sessions"
    __table_args__ = (
        Index("ix_dream_sessions_started_at", text("started_at DESC")),
    )

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    anima_id: UUID = Field(
        foreign_key="animas.id",
        index=True,
        description="Anima being dreamed for"
    )

    # Trigger metadata
    trigger_type: DreamTriggerType = Field(
        description="How the dream was initiated (SCHEDULED or MANUAL)"
    )
    triggered_by: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        description="User who triggered (NULL for scheduled)"
    )

    # Timing
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When dream execution began"
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When dream finished (success or failure)"
    )

    # Status
    status: DreamStatus = Field(
        default=DreamStatus.RUNNING,
        index=True,
        description="Current state of the dream"
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if FAILED"
    )

    # Metrics
    memories_reviewed: int = Field(
        default=0,
        description="Total memories examined"
    )
    memories_modified: int = Field(
        default=0,
        description="Memories updated (includes merge sources)"
    )
    memories_created: int = Field(
        default=0,
        description="New memories from merges/splits"
    )
    memories_archived: int = Field(
        default=0,
        description="Memories transitioned to DECAYING/ARCHIVED"
    )
    memories_deleted: int = Field(
        default=0,
        description="Memories soft-deleted as noise"
    )

    # LLM-generated summary
    summary: str | None = Field(
        default=None,
        description="Human-readable summary of what happened"
    )

    # Frozen config at dream time
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'")),
        description="DreamerConfig values at execution time"
    )

    # Relationships
    actions: list["DreamAction"] = Relationship(back_populates="session")
    anima: Optional["Anima"] = Relationship()
    triggered_by_user: Optional["User"] = Relationship()


class DreamAction(SQLModel, table=True):
    """
    Individual action taken during a dream session.

    Each action records before/after snapshots for audit trail and rollback.
    """
    __tablename__ = "dream_actions"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    session_id: UUID = Field(
        sa_column=Column(
            ForeignKey("dream_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        ),
        description="Parent dream session"
    )

    # Action metadata
    action_type: DreamActionType = Field(
        index=True,
        description="Type of action (MERGE, SPLIT, UPDATE, ARCHIVE, DELETE)"
    )
    phase: DreamPhase = Field(
        description="Which phase produced this action"
    )

    # Affected memories (stored as UUID arrays)
    source_memory_ids: list[UUID] = Field(
        sa_column=Column(ARRAY(PGUUID), nullable=False),
        description="Original memory IDs before action"
    )
    result_memory_ids: list[UUID] | None = Field(
        default=None,
        sa_column=Column(ARRAY(PGUUID), nullable=True),
        description="Resulting memory IDs after action (NULL for DELETE)"
    )

    # Snapshots for audit/rollback
    before_state: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
        description="Snapshot of source memories before change"
    )
    after_state: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
        description="Snapshot of result memories after change (NULL for DELETE)"
    )

    # LLM reasoning (NULL for algorithmic Light Sleep actions)
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
    session: Optional[DreamSession] = Relationship(back_populates="actions")
