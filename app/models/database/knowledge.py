from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Text, CheckConstraint, text
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin
from app.models.database.animas import Anima

if TYPE_CHECKING:
    from app.models.database.knowledge_audit_log import KnowledgeAuditLog


class KnowledgeType(str, Enum):
    """Five fundamental modes of knowing (epistemic types)."""
    FACT = "FACT"               # Verifiable truth about external world
    CONCEPT = "CONCEPT"         # Abstract framework or model
    METHOD = "METHOD"           # Procedural/causal understanding
    PRINCIPLE = "PRINCIPLE"     # Guiding normative belief
    EXPERIENCE = "EXPERIENCE"   # Personal, lived knowledge


class SourceType(str, Enum):
    """Knowledge source classification."""
    INTERNAL = "INTERNAL"       # Derived from Memories/Events
    EXTERNAL = "EXTERNAL"       # Imported/provided externally


class AuditAction(str, Enum):
    """Audit log action types."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    RESTORE = "RESTORE"


class Knowledge(TimestampMixin, table=True):
    """
    Crystallized understanding - the intellectual core of an Anima.

    Represents stable, reusable knowledge distilled from Memories through
    LLM synthesis. Organized by epistemic type and practical topic grouping.
    Inherits created_at, updated_at from TimestampMixin.
    """
    __tablename__ = "knowledge"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    anima_id: UUID = Field(foreign_key="animas.id", index=True)
    knowledge_type: KnowledgeType = Field(index=True)
    topic: Optional[str] = Field(default=None, index=True)  # LLM-controlled grouping
    content: str = Field(sa_column=Column(Text))  # Main knowledge statement
    summary: Optional[str] = Field(default=None)  # Compact one-liner
    confidence: Optional[float] = Field(default=None)  # 0.0-1.0 certainty
    source_type: SourceType = Field(default=SourceType.INTERNAL)
    is_deleted: bool = Field(default=False, index=True)

    # Vector embedding for semantic search (1536 dims = text-embedding-3-small)
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(1536), nullable=True))
    embedding_model: str | None = Field(default=None, max_length=50)

    # Relationships
    anima: "Anima" = Relationship(back_populates="knowledge")
    audit_logs: list["KnowledgeAuditLog"] = Relationship(back_populates="knowledge")

    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="check_confidence_range"),
    )


class KnowledgeBase(SQLModel):
    """Shared fields for Knowledge operations."""
    anima_id: UUID = Field(foreign_key="animas.id")
    knowledge_type: KnowledgeType
    topic: Optional[str] = Field(default=None)
    content: str
    summary: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_type: SourceType = Field(default=SourceType.INTERNAL)


class KnowledgeCreate(KnowledgeBase):
    """Data required to create a Knowledge entry."""
    pass


class KnowledgeRead(KnowledgeBase):
    """Data returned when reading a Knowledge entry."""
    id: UUID
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    embedding_model: str | None = None


class KnowledgeUpdate(SQLModel):
    """Fields that can be updated (partial update support)."""
    knowledge_type: Optional[KnowledgeType] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    topic: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_type: Optional[SourceType] = None
