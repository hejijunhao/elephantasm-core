"""Events model - atomic units of experience in Elephantasm."""

from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin
from app.models.database.animas import Anima

if TYPE_CHECKING:
    from app.models.database.memories_events import MemoryEvent


class EventType(str, Enum):
    """Event types for alpha release (messages only)."""
    MESSAGE_IN = "message.in"
    MESSAGE_OUT = "message.out"
    # Future: TOOL_CALL, TOOL_RESULT, FILE_INGESTED, etc.


class EventBase(SQLModel):
    """Shared fields for Event model."""
    anima_id: UUID = Field(foreign_key="animas.id", index=True, description="Owner anima ID")
    event_type: str = Field(max_length=100, index=True)
    role: str | None = Field(default=None, max_length=50, index=True, description="Message role: user, assistant, system, tool", nullable=True)
    author: str | None = Field(default=None, max_length=255, description="Author identifier (username, tool name, model name)", nullable=True)
    summary: str | None = Field(default=None, description="Brief summary", nullable=True)
    content: str = Field(description="Human-readable message content")
    occurred_at: datetime | None = Field(default=None, description="When event occurred (source time)", nullable=True)
    session_id: str | None = Field(default=None, max_length=255, index=True, nullable=True)
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    source_uri: str | None = Field(default=None, nullable=True)
    dedupe_key: str | None = Field(default=None, max_length=255, nullable=True)
    importance_score: float | None = Field(default=None, ge=0.0, le=1.0, nullable=True)


class Event(EventBase, TimestampMixin, table=True):
    """Event entity - atomic unit of experience."""
    __tablename__ = "events"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False)

    # Relationship to Anima
    anima: Anima = Relationship(back_populates="events")

    # Relationship to MemoryEvents (provenance)
    memory_links: list["MemoryEvent"] = Relationship(back_populates="event")


class EventCreate(EventBase):
    """Data required to create an Event."""
    pass


class EventRead(EventBase):
    """Data returned when reading an Event."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class EventUpdate(SQLModel):
    """Fields that can be updated."""
    role: str | None = None
    author: str | None = None
    meta: dict[str, Any] | None = None
    importance_score: float | None = None
    summary: str | None = None
    is_deleted: bool | None = None
