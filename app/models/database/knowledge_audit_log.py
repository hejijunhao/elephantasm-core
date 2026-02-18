from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.knowledge import AuditAction, SourceType

if TYPE_CHECKING:
    from app.models.database.knowledge import Knowledge


class KnowledgeAuditLog(SQLModel, table=True):
    """
    Immutable audit trail for Knowledge changes.

    Serves dual purpose:
    1. Change tracking: Before/after state snapshots
    2. Provenance: Links to source Memories that triggered changes
    """
    __tablename__ = "knowledge_audit_log"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    knowledge_id: UUID = Field(foreign_key="knowledge.id", index=True)
    action: AuditAction = Field(index=True)
    source_type: Optional[SourceType] = Field(default=None)  # What triggered change
    source_id: Optional[UUID] = Field(default=None, foreign_key="memories.id", index=True)  # Memory UUID if memory-triggered
    before_state: Optional[dict] = Field(default=None, sa_column=Column(JSONB))
    after_state: dict = Field(sa_column=Column(JSONB))
    change_summary: Optional[str] = Field(default=None)  # Human/LLM description of change
    triggered_by: Optional[str] = Field(default=None)  # "synthesis_workflow", "user:123", "manual"
    created_at: datetime = Field(
        default=None,
        index=True,
        sa_column_kwargs={"server_default": text("now()")}
    )

    # Relationships
    knowledge: "Knowledge" = Relationship(back_populates="audit_logs")


# Audit Log DTOs

class AuditLogBase(SQLModel):
    """Shared fields for audit log operations."""
    knowledge_id: UUID = Field(foreign_key="knowledge.id")
    action: AuditAction
    source_type: Optional[SourceType] = Field(default=None)
    source_id: Optional[UUID] = Field(default=None, foreign_key="memories.id")
    before_state: Optional[dict] = Field(default=None)
    after_state: dict
    change_summary: Optional[str] = Field(default=None)
    triggered_by: Optional[str] = Field(default=None)


class AuditLogCreate(AuditLogBase):
    """Data required to create an audit log entry."""
    pass


class AuditLogRead(AuditLogBase):
    """Data returned when reading an audit log entry."""
    id: UUID
    created_at: datetime
