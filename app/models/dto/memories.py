"""DTOs for Memory map/visualization endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryMapPoint(BaseModel):
    """A memory with UMAP-projected 2D coordinates for constellation rendering."""

    id: UUID
    summary: str | None = None
    content: str | None = None
    importance: float | None = None
    confidence: float | None = None
    state: str | None = None
    recency_score: float | None = None
    decay_score: float | None = None
    created_at: datetime
    x: float = Field(description="UMAP-projected X coordinate [0, 1]")
    y: float = Field(description="UMAP-projected Y coordinate [0, 1]")

    model_config = {"from_attributes": True}
