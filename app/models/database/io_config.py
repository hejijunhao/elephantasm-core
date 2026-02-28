"""IOConfig model - per-anima I/O configuration for event capture and pack compilation."""

from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.animas import Anima


# Default settings for new IOConfigs
DEFAULT_READ_SETTINGS: dict[str, Any] = {
    "event_types": ["message.in", "message.out", "tool.call", "system"],
    "session_timeout_minutes": 30,
    "dedupe_window_minutes": 5,
    "min_content_length": 0,
    "source_filters": {"include": [], "exclude": []},
    "importance_rules": [],
}

DEFAULT_WRITE_SETTINGS: dict[str, Any] = {
    "preset": "conversational",
    "weights": {
        "importance": 0.25,
        "confidence": 0.15,
        "recency": 0.20,
        "decay": 0.15,
        "similarity": 0.25,
    },
    "limits": {
        "session_memories": 5,
        "knowledge": 10,
        "long_term_memories": 10,
    },
    "token_budget": 4000,
    "session_window_hours": 24,
    "similarity_threshold": 0.7,
    "min_importance": None,
    "include_identity": True,
    "injection": {
        "trigger": "every_turn",
        "cooldown_seconds": 0,
        "drift_detection": False,
    },
}


class IOConfigBase(SQLModel):
    """Shared fields for IOConfig model."""

    anima_id: UUID = Field(
        foreign_key="animas.id",
        unique=True,
        index=True,
        description="Owner anima ID (one-to-one)",
    )
    read_settings: dict[str, Any] = Field(
        default_factory=lambda: DEFAULT_READ_SETTINGS.copy(),
        sa_column=Column(JSONB, nullable=False),
        description="Inbound event capture configuration",
    )
    write_settings: dict[str, Any] = Field(
        default_factory=lambda: DEFAULT_WRITE_SETTINGS.copy(),
        sa_column=Column(JSONB, nullable=False),
        description="Outbound pack compilation configuration",
    )


class IOConfig(IOConfigBase, TimestampMixin, table=True):
    """Per-anima I/O configuration. One-to-one relationship with Anima."""

    __tablename__ = "io_configs"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )

    # Relationships
    anima: "Anima" = Relationship(back_populates="io_config")


class IOConfigRead(SQLModel):
    """Response model for IOConfig."""

    id: UUID
    anima_id: UUID
    read_settings: dict[str, Any]
    write_settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IOConfigUpdate(SQLModel):
    """Update model for IOConfig (partial updates via merge)."""

    read_settings: dict[str, Any] | None = None
    write_settings: dict[str, Any] | None = None


class IOConfigDefaultsResponse(SQLModel):
    """Response model for default settings endpoint."""

    read_settings: dict[str, Any]
    write_settings: dict[str, Any]
