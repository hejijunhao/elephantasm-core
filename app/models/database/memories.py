"""Memories model - subjective interpretation of Events in Elephantasm."""

from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin
from app.models.database.animas import Anima

if TYPE_CHECKING:
    from app.models.database.memories_events import MemoryEvent


class MemoryState(str, Enum):
    """Lifecycle states for memory recall and curation."""
    ACTIVE = "active"         # Actively recalled, high attention
    DECAYING = "decaying"     # Fading from active recall
    ARCHIVED = "archived"     # Preserved but rarely recalled


class MemoryBase(SQLModel):
    """Shared fields for Memory model."""
    anima_id: UUID = Field(foreign_key="animas.id", index=True, description="Owner anima ID")
    content: str | None = Field(default=None, nullable=True, description="Full memory content")
    summary: str | None = Field(default=None, nullable=True, description="Compact narrative essence of the memory")
    importance: float | None = Field(default=None, ge=0.0, le=1.0, index=True, nullable=True, description="Weight in recall/curation priority (0.0-1.0)")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, nullable=True, description="Stability/certainty of the memory (0.0-1.0)")
    state: MemoryState | None = Field(default=None, index=True, nullable=True, description="Lifecycle state (active/decaying/archived)")
    recency_score: float | None = Field(default=None, ge=0.0, le=1.0, nullable=True, description="Cached temporal freshness (optional)")
    decay_score: float | None = Field(default=None, ge=0.0, le=1.0, nullable=True, description="Cached fading score (optional)")
    time_start: datetime | None = Field(default=None, nullable=True, description="When underlying events began")
    time_end: datetime | None = Field(default=None, index=True, nullable=True, description="When underlying events ended (for recency calculation)")
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=True), description="Topics, tags, curator signals")


class Memory(MemoryBase, TimestampMixin, table=True):
    """Memory entity - subjective interpretation of Events. Inherits created_at, updated_at from TimestampMixin."""
    __tablename__ = "memories"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False, description="Soft delete flag (provenance preservation)")

    # Vector embedding for semantic search (1536 dims = text-embedding-3-small)
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(1536), nullable=True))
    embedding_model: str | None = Field(default=None, max_length=50, description="Model used to generate embedding")

    # Relationship to Anima
    anima: Anima = Relationship(back_populates="memories")

    # Relationship to MemoryEvents (provenance)
    event_links: list["MemoryEvent"] = Relationship(back_populates="memory")


class MemoryCreate(MemoryBase):
    """Data required to create a Memory (inherits all MemoryBase fields)."""
    pass


class MemoryRead(MemoryBase):
    """Data returned when reading a Memory."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    embedding_model: str | None = None


class MemoryUpdate(SQLModel):
    """Fields that can be updated (partial update support)."""
    content: str | None = None
    summary: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    recency_score: float | None = Field(default=None, ge=0.0, le=1.0)
    decay_score: float | None = Field(default=None, ge=0.0, le=1.0)
    state: MemoryState | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    meta: dict[str, Any] | None = None
    is_deleted: bool | None = None
