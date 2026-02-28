"""MemoryPack model - persisted memory packs for observability and provenance."""

from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.animas import Anima


class MemoryPackBase(SQLModel):
    """Shared fields for MemoryPack model."""

    anima_id: UUID = Field(
        foreign_key="animas.id",
        index=True,
        description="Owner anima ID",
    )

    # Query context
    query: Optional[str] = Field(
        default=None,
        description="Query used for semantic retrieval",
    )
    preset_name: Optional[str] = Field(
        default=None,
        description="Preset used: conversational, self_determined, or None (custom)",
    )

    # Layer counts (denormalized for quick stats)
    session_memory_count: int = Field(
        default=0,
        description="Number of session memories included",
    )
    knowledge_count: int = Field(
        default=0,
        description="Number of knowledge items included",
    )
    long_term_memory_count: int = Field(
        default=0,
        description="Number of long-term memories included",
    )
    has_identity: bool = Field(
        default=False,
        description="Whether identity was included",
    )

    # Token budget
    token_count: int = Field(
        default=0,
        description="Estimated token count of pack",
    )
    max_tokens: int = Field(
        default=4000,
        description="Token budget used for compilation",
    )

    # Full pack content (serialized JSON)
    content: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
        description="Serialized pack content: context, identity, memories, knowledge, config",
    )
    # Content structure:
    # {
    #   "context": "formatted prompt string",
    #   "identity": { personality_type, communication_style, self_reflection },
    #   "session_memories": [{ id, summary, score, reason, breakdown }],
    #   "knowledge": [{ id, content, type, score, similarity }],
    #   "long_term_memories": [{ id, summary, score, reason, breakdown, similarity }],
    #   "config": { retrieval config used }
    # }

    # Timestamp for when pack was compiled
    compiled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this pack was compiled",
    )


class MemoryPack(MemoryPackBase, TimestampMixin, table=True):
    """Persisted memory pack for observability and provenance."""

    __tablename__ = "memory_packs"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )

    # Relationships
    anima: "Anima" = Relationship(back_populates="memory_packs")


class MemoryPackRead(SQLModel):
    """Response model for MemoryPack."""

    id: UUID
    anima_id: UUID
    query: Optional[str]
    preset_name: Optional[str]
    session_memory_count: int
    knowledge_count: int
    long_term_memory_count: int
    has_identity: bool
    token_count: int
    max_tokens: int
    content: dict[str, Any]
    compiled_at: datetime
    created_at: datetime


class MemoryPackStats(SQLModel):
    """Statistics response for memory packs."""

    total_packs: int = Field(description="Total packs compiled for anima")
    avg_token_count: float = Field(description="Average token usage")
    avg_session_memories: float = Field(description="Average session memories per pack")
    avg_knowledge: float = Field(description="Average knowledge items per pack")
    avg_long_term_memories: float = Field(description="Average long-term memories per pack")
    identity_usage_rate: float = Field(description="Percentage of packs with identity")
