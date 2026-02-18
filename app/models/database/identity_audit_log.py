"""Identity audit log model - immutable trail for identity evolution."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, Relationship

if TYPE_CHECKING:
    from app.models.database.identity import Identity


class IdentityAuditAction(str, Enum):
    """Identity audit log action types."""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    RESTORE = "RESTORE"
    ASSESS = "ASSESS"    # Personality assessment/reassessment
    EVOLVE = "EVOLVE"    # Dreamer-driven evolution


class IdentityAuditLog(SQLModel, table=True):
    """
    Immutable audit trail for Identity changes.

    Tracks personality evolution over time with before/after snapshots
    and provenance links to source memories.
    """
    __tablename__ = "identity_audit_log"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    identity_id: UUID = Field(foreign_key="identities.id", index=True)

    # Change tracking
    action: IdentityAuditAction = Field(index=True)
    trigger_source: Optional[str] = Field(default=None, max_length=50)  # 'dreamer', 'manual', 'synthesis'
    source_memory_id: Optional[UUID] = Field(default=None, foreign_key="memories.id", index=True)

    # State snapshots
    before_state: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    after_state: dict[str, Any] = Field(sa_column=Column(JSONB))

    # Human/LLM description of change
    change_summary: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Immutable timestamp (no updated_at - audit logs are append-only)
    created_at: datetime = Field(
        default=None,
        index=True,
        sa_column_kwargs={"server_default": text("now()")}
    )

    # Relationships
    identity: Optional["Identity"] = Relationship(back_populates="audit_logs")


# DTOs

class IdentityAuditLogBase(SQLModel):
    """Shared fields for audit log operations."""
    identity_id: UUID
    action: IdentityAuditAction
    trigger_source: Optional[str] = None
    source_memory_id: Optional[UUID] = None
    before_state: Optional[dict[str, Any]] = None
    after_state: dict[str, Any]
    change_summary: Optional[str] = None


class IdentityAuditLogCreate(IdentityAuditLogBase):
    """Data required to create an identity audit log entry."""
    pass


class IdentityAuditLogRead(IdentityAuditLogBase):
    """Data returned when reading an identity audit log entry."""
    id: UUID
    created_at: datetime
