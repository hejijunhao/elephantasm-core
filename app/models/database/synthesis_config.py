"""Synthesis Configuration model - per-anima memory synthesis parameters."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.animas import Anima


class SynthesisConfigBase(SQLModel):
    """Shared fields for SynthesisConfig model."""
    anima_id: UUID = Field(foreign_key="animas.id", unique=True, index=True, description="Owner anima ID (one-to-one)")
    time_weight: float = Field(default=1.0, ge=0.0, le=5.0, description="Points per hour (0.0-5.0)")
    event_weight: float = Field(default=0.5, ge=0.0, le=2.0, description="Points per event (0.0-2.0)")
    token_weight: float = Field(default=0.0003, ge=0.0, le=0.001, description="Points per token (0.0-0.001)")
    threshold: float = Field(default=10.0, ge=1.0, le=50.0, description="Accumulation score threshold (1.0-50.0)")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="LLM temperature for synthesis (0.0-1.0)")
    max_tokens: int = Field(default=1024, ge=256, le=4096, description="Max tokens for LLM response (256-4096)")
    job_interval_hours: int = Field(default=1, ge=1, le=24, description="Hours between synthesis jobs (1-24)")


class SynthesisConfig(SynthesisConfigBase, TimestampMixin, table=True):
    """Memory synthesis configuration for an anima. One-to-one relationship with Anima."""
    __tablename__ = "synthesis_configs"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    last_synthesis_check_at: datetime | None = Field(
        default=None,
        nullable=True,
        description="Last time synthesis threshold was checked (skip or proceed)"
    )
    anima: "Anima" = Relationship(back_populates="synthesis_config")


class SynthesisConfigRead(SynthesisConfigBase):
    """Response model for synthesis config."""
    id: UUID
    last_synthesis_check_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SynthesisConfigUpdate(SQLModel):
    """Update model for synthesis config (all fields optional)."""
    time_weight: float | None = Field(None, ge=0.0, le=5.0)
    event_weight: float | None = Field(None, ge=0.0, le=2.0)
    token_weight: float | None = Field(None, ge=0.0, le=0.001)
    threshold: float | None = Field(None, ge=1.0, le=50.0)
    temperature: float | None = Field(None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=256, le=4096)
    job_interval_hours: int | None = Field(None, ge=1, le=24)


class SynthesisStatusResponse(SQLModel):
    """Response model for synthesis status endpoint (current score vs threshold)."""
    accumulation_score: float = Field(description="Current accumulation score")
    threshold: float = Field(description="Configured threshold for synthesis trigger")
    percentage: float = Field(description="Score as percentage of threshold (0-100+)")
    time_factor: float = Field(description="Time component of score (hours × weight)")
    event_factor: float = Field(description="Event component of score (events × weight)")
    token_factor: float = Field(description="Token component of score (tokens × weight)")
    event_count: int = Field(description="Raw event count since last memory")
    hours_since_last: float = Field(description="Hours since last memory creation")
