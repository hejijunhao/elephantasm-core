"""
Injection response DTOs for Pack Compilation API.

Defines response models for pack compilation endpoints.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class ScoredMemoryResponse(BaseModel):
    """Serialized scored memory for API response."""

    id: UUID
    summary: Optional[str] = None
    score: float = Field(description="Combined retrieval score (0-1)")
    retrieval_reason: str = Field(description="Why this memory was included")
    similarity: Optional[float] = Field(
        default=None, description="Semantic similarity to query (0-1)"
    )
    time_start: Optional[datetime] = None
    score_breakdown: Optional[Dict[str, float]] = Field(
        default=None, description="Individual score components"
    )

    model_config = {"from_attributes": True}


class ScoredKnowledgeResponse(BaseModel):
    """Serialized scored knowledge for API response."""

    id: UUID
    content: str
    knowledge_type: str
    score: float = Field(description="Retrieval score (0-1)")
    similarity: Optional[float] = Field(
        default=None, description="Semantic similarity to query (0-1)"
    )

    model_config = {"from_attributes": True}


class IdentitySummaryResponse(BaseModel):
    """Serialized identity summary for API response."""

    name: Optional[str] = None
    personality_type: Optional[str] = None
    communication_style: Optional[str] = None
    self_reflection: Optional[Dict[str, Any]] = None


class TemporalContextResponse(BaseModel):
    """Serialized temporal context for API response."""

    last_event_at: datetime = Field(description="When the most recent event occurred")
    hours_ago: float = Field(description="Hours since last event")
    memory_summary: Optional[str] = Field(
        default=None, description="Summary of the memory linked to last event (if any)"
    )
    formatted: str = Field(description="Pre-composed string for injection")


class PackResponse(BaseModel):
    """API response for compiled pack."""

    # Metadata
    anima_id: UUID
    query: Optional[str] = None
    compiled_at: datetime
    token_count: int = Field(description="Estimated token count")

    # Layer counts (quick summary)
    session_memory_count: int
    knowledge_count: int
    long_term_memory_count: int
    has_identity: bool
    has_temporal_context: bool = Field(
        default=False, description="Whether temporal awareness context was included"
    )

    # Formatted context (ready for LLM injection)
    context: str = Field(description="Formatted prompt context string")

    # Detailed breakdown (for debugging/UI)
    identity: Optional[IdentitySummaryResponse] = None
    temporal_context: Optional[TemporalContextResponse] = Field(
        default=None, description="Temporal awareness context (present when session is empty)"
    )
    session_memories: List[ScoredMemoryResponse] = Field(default_factory=list)
    knowledge: List[ScoredKnowledgeResponse] = Field(default_factory=list)
    long_term_memories: List[ScoredMemoryResponse] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "anima_id": "123e4567-e89b-12d3-a456-426614174000",
                    "query": "What are the user's preferences?",
                    "compiled_at": "2025-12-06T12:00:00Z",
                    "token_count": 1250,
                    "session_memory_count": 3,
                    "knowledge_count": 5,
                    "long_term_memory_count": 7,
                    "has_identity": True,
                    "context": "## Your Identity\nPersonality: INTJ\n\n## Current Session\n- Recent discussion...",
                }
            ]
        }
    }


class PackPreviewResponse(BaseModel):
    """Lightweight preview response (counts + scores only)."""

    session_memory_count: int
    knowledge_count: int
    long_term_memory_count: int
    has_identity: bool
    has_temporal_context: bool = False
    token_count: int

    # Top scores for each layer (for debugging)
    top_session_scores: List[float] = Field(
        default_factory=list, description="Top 3 session memory scores"
    )
    top_knowledge_scores: List[float] = Field(
        default_factory=list, description="Top 3 knowledge scores"
    )
    top_longterm_scores: List[float] = Field(
        default_factory=list, description="Top 3 long-term memory scores"
    )
