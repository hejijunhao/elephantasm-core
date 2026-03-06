"""Log entry DTOs for unified activity timeline."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class LogEntityType(str, Enum):
    """Types of entities tracked in the activity log."""
    EVENT = "event"
    MEMORY = "memory"
    DREAM_SESSION = "dream_session"
    DREAM_ACTION = "dream_action"
    MEMORY_PACK = "memory_pack"
    KNOWLEDGE = "knowledge"
    IDENTITY_AUDIT = "identity_audit"
    KNOWLEDGE_AUDIT = "knowledge_audit"


class LogEntry(BaseModel):
    """Single entry in the unified activity log."""
    id: UUID
    entity_type: LogEntityType
    timestamp: datetime
    title: str
    summary: Optional[str] = None
    icon: str
    color: str
    entity_id: UUID
    anima_id: UUID
    meta: Optional[dict[str, Any]] = None


class LogsResponse(BaseModel):
    """Paginated logs response."""
    entries: list[LogEntry]
    total: int
    has_more: bool
    limit: int
    offset: int


class LogStats(BaseModel):
    """Count of log entries per type."""
    total: int = 0
    event: int = 0
    memory: int = 0
    dream_session: int = 0
    dream_action: int = 0
    memory_pack: int = 0
    knowledge: int = 0
    identity_audit: int = 0
    knowledge_audit: int = 0
