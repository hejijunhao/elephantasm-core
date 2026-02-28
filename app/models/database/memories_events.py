"""Memory-Event Link model - provenance junction table."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from app.models.database.memories import Memory
    from app.models.database.events import Event


class MemoryEventBase(SQLModel):
    """Shared fields for MemoryEvent model."""
    memory_id: UUID = Field(
        sa_column=Column(
            SA_UUID,
            ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        ),
        description="Memory ID"
    )
    event_id: UUID = Field(
        sa_column=Column(
            SA_UUID,
            ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        ),
        description="Event ID"
    )
    link_strength: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        index=True,
        nullable=True,
        description="Weight of this event's contribution (0.0-1.0)"
    )


class MemoryEvent(MemoryEventBase, table=True):
    """Junction table linking Memories to their source Events."""
    __tablename__ = "memories_events"
    __table_args__ = (
        UniqueConstraint("memory_id", "event_id", name="uq_memories_events_memory_event"),
        CheckConstraint("link_strength >= 0.0 AND link_strength <= 1.0", name="ck_link_strength_range"),
    )

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column_kwargs={"nullable": False}, description="When this link was created (immutable)")

    # Relationships
    memory: "Memory" = Relationship(back_populates="event_links")
    event: "Event" = Relationship(back_populates="memory_links")


class MemoryEventCreate(MemoryEventBase):
    """Data required to create a link (memory_id + event_id required)."""
    pass


class MemoryEventRead(MemoryEventBase):
    """Data returned when reading a link."""
    id: UUID
    created_at: datetime


class MemoryEventUpdate(SQLModel):
    """Fields that can be updated (realistically, links are mostly immutable)."""
    link_strength: float | None = Field(default=None, ge=0.0, le=1.0)
