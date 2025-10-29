"""Animas model - the owner entity in Elephantasm."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin


class AnimaBase(SQLModel):
    """Shared fields for Anima model."""
    name: str = Field(max_length=255, description="Human-readable anima name")
    description: str | None = Field(default=None, nullable=True, description="Brief description")
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))


class Anima(AnimaBase, TimestampMixin, table=True):
    """Anima entity - represents an owner of memories."""
    __tablename__ = "animas"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False)

    # Relationships
    events: list["Event"] = Relationship(back_populates="anima")
    memories: list["Memory"] = Relationship(back_populates="anima")


class AnimaCreate(AnimaBase):
    """Data required to create an Anima."""
    pass


class AnimaRead(AnimaBase):
    """Data returned when reading an Anima."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class AnimaUpdate(SQLModel):
    """Fields that can be updated."""
    name: str | None = None
    description: str | None = None
    meta: dict[str, Any] | None = None
    is_deleted: bool | None = None
