"""Animas model - the owner entity in Elephantasm."""

from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.synthesis_config import SynthesisConfig
    from app.models.database.user import User
    from app.models.database.organization import Organization
    from app.models.database.knowledge import Knowledge
    from app.models.database.memories import Memory
    from app.models.database.events import Event
    from app.models.database.identity import Identity
    from app.models.database.io_config import IOConfig
    from app.models.database.memory_pack import MemoryPack


class AnimaBase(SQLModel):
    """Shared fields for Anima model."""
    name: str = Field(max_length=255, description="Human-readable anima name")
    description: str | None = Field(default=None, nullable=True, description="Brief description")
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True, nullable=True, description="Owner user reference (RLS filtering)")
    organization_id: UUID | None = Field(default=None, foreign_key="organizations.id", index=True, nullable=True, description="Owning organization (org-scoped access)")

    # Dormancy tracking (computed daily: dormant = no activity for 30+ days)
    is_dormant: bool = Field(default=False, index=True, description="True if no activity in 30+ days")
    last_activity_at: datetime | None = Field(default=None, nullable=True, description="Last event or pack build timestamp")


class Anima(AnimaBase, TimestampMixin, table=True):
    """Anima entity - represents an owner of memories."""
    __tablename__ = "animas"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="animas")
    organization: Optional["Organization"] = Relationship(back_populates="animas")
    events: list["Event"] = Relationship(back_populates="anima")
    memories: list["Memory"] = Relationship(back_populates="anima")
    knowledge: list["Knowledge"] = Relationship(back_populates="anima")
    synthesis_config: "SynthesisConfig" = Relationship(
        back_populates="anima",
        sa_relationship_kwargs={"uselist": False}  # One-to-one
    )
    identity: Optional["Identity"] = Relationship(
        back_populates="anima",
        sa_relationship_kwargs={"uselist": False}  # One-to-one
    )
    io_config: Optional["IOConfig"] = Relationship(
        back_populates="anima",
        sa_relationship_kwargs={"uselist": False}  # One-to-one
    )
    memory_packs: list["MemoryPack"] = Relationship(back_populates="anima")


class AnimaCreate(SQLModel):
    """Data required to create an Anima. user_id excluded (set from JWT)."""
    name: str = Field(max_length=255, description="Human-readable anima name")
    description: str | None = Field(default=None, nullable=True, description="Brief description")
    meta: dict[str, Any] | None = Field(default=None)
    organization_id: UUID | None = Field(default=None, description="Target org (resolved from context if not provided)")


class AnimaRead(AnimaBase):
    """Data returned when reading an Anima."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class AnimaUpdate(SQLModel):
    """Fields that can be updated. user_id excluded (immutable after creation)."""
    name: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    is_deleted: bool | None = None


class AnimaSummary(SQLModel):
    """Anima with inline stats for library card grid. Populated via scalar subqueries."""
    id: UUID
    name: str
    description: str | None = None
    organization_id: UUID | None = None
    is_dormant: bool
    last_activity_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Inline stats
    event_count: int = 0
    memory_count: int = 0
    knowledge_count: int = 0
    last_event_at: datetime | None = None
