"""
DTOs for unified /query endpoint.

Provides cross-source brain search with token-budgeted results.
"""

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    """Optional time window for recency-scoped retrieval."""

    after: Optional[datetime] = Field(
        default=None, description="Include results after this time"
    )
    before: Optional[datetime] = Field(
        default=None, description="Include results before this time"
    )


class QueryRequest(BaseModel):
    """Unified brain query request."""

    anima_id: UUID = Field(description="Anima to query")
    query: str = Field(min_length=1, description="Natural language query")
    sources: List[Literal["memories", "knowledge", "identity"]] = Field(
        default=["memories", "knowledge", "identity"],
        description="Which layers to search",
    )
    max_tokens: int = Field(
        default=2000,
        ge=100,
        le=16000,
        description="Token budget for results",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max result count",
    )
    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold",
    )
    time_range: Optional[TimeRange] = Field(
        default=None,
        description="Filter results by time window",
    )
    exclude_ids: Optional[List[UUID]] = Field(
        default=None,
        description="Skip previously seen results (for multi-turn loops)",
    )


class QueryResult(BaseModel):
    """Single result from cross-source brain search."""

    id: UUID
    source: Literal["memory", "knowledge"]
    content: str
    similarity: float = Field(description="Cosine similarity to query (0-1)")
    type: Optional[str] = Field(
        default=None, description="Knowledge type (FACT, CONCEPT, etc.)"
    )
    topic: Optional[str] = Field(
        default=None, description="Knowledge topic"
    )
    importance: Optional[float] = Field(
        default=None, description="Memory importance (0-1)"
    )
    confidence: Optional[float] = Field(
        default=None, description="Confidence score (0-1)"
    )
    time_start: Optional[datetime] = Field(
        default=None, description="Memory time start"
    )


class IdentityContextResponse(BaseModel):
    """Identity snapshot for query response."""

    personality_type: Optional[str] = None
    communication_style: Optional[str] = None
    self_reflection: Optional[dict[str, Any]] = None


class QueryResponse(BaseModel):
    """Unified brain query response with dual format."""

    results: List[QueryResult] = Field(
        description="Structured results sorted by similarity"
    )
    identity_context: Optional[IdentityContextResponse] = Field(
        default=None, description="Identity snapshot (if requested)"
    )
    context: str = Field(
        description="Pre-formatted prompt context string"
    )
    token_estimate: int = Field(
        description="Estimated token count of context string"
    )
