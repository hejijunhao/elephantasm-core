"""
Retrieval configuration DTOs for Pack Compilation.

Defines the request model for configuring how memory packs are assembled.
"""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from uuid import UUID

from app.models.database.memories import MemoryState
from app.models.database.knowledge import KnowledgeType


class TemporalContext(BaseModel):
    """
    Temporal awareness context for bridging session gaps.

    When session_memories is empty (user returns after a gap),
    this provides context about when the last interaction occurred.
    """

    last_event_at: datetime = Field(description="When the most recent event occurred")
    hours_ago: float = Field(description="Hours since last event")
    memory_summary: Optional[str] = Field(
        default=None, description="Summary of the memory linked to last event (if any)"
    )
    formatted: str = Field(description="Pre-composed string for injection")

    model_config = {"json_schema_extra": {"examples": [
        {
            "last_event_at": "2025-12-13T14:30:00Z",
            "hours_ago": 48.5,
            "memory_summary": "discussing project deadline concerns",
            "formatted": "Your last communication with the user was 2 days ago about discussing project deadline concerns.",
        }
    ]}}


class RetrievalConfig(BaseModel):
    """
    Configuration for pack compilation.

    Controls what content is retrieved and how it's scored.
    """

    # === Target ===
    anima_id: UUID = Field(description="Anima to retrieve memories for")
    query: Optional[str] = Field(
        default=None,
        description="Query for semantic search (required for knowledge/long-term layers)",
    )

    # === Session Configuration ===
    session_window_hours: int = Field(
        default=24,
        ge=1,
        le=168,  # 1 hour to 1 week
        description="Time window for session memories (hours)",
    )

    # === Filters ===
    memory_states: List[MemoryState] = Field(
        default=[MemoryState.ACTIVE],
        description="Memory states to include (for long-term memories)",
    )
    knowledge_types: Optional[List[KnowledgeType]] = Field(
        default=None,
        description="Knowledge types to include (None = all types)",
    )
    min_importance: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum importance threshold (0-1)",
    )
    min_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold (0-1)",
    )

    # === Limits (per layer) ===
    max_session_memories: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Max session memories to retrieve",
    )
    max_knowledge: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Max knowledge items to retrieve",
    )
    max_long_term_memories: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Max long-term memories to retrieve",
    )
    max_tokens: int = Field(
        default=4000,
        ge=500,
        le=16000,
        description="Token budget for entire pack",
    )

    # === Scoring Weights (long-term memories only) ===
    weight_importance: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Weight for memory importance",
    )
    weight_confidence: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Weight for memory confidence",
    )
    weight_recency: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Weight for recency score",
    )
    weight_decay: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Weight for (1 - decay) score",
    )
    weight_similarity: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Weight for semantic similarity",
    )

    # === Semantic Search ===
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity to include (0-1)",
    )

    # === Options ===
    include_identity: bool = Field(
        default=True,
        description="Include identity layer in pack",
    )
    include_temporal_awareness: bool = Field(
        default=True,
        description="Include temporal context when session memories empty (bridges gaps)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "anima_id": "123e4567-e89b-12d3-a456-426614174000",
                    "query": "What are the user's preferences?",
                    "session_window_hours": 24,
                    "max_session_memories": 5,
                    "max_knowledge": 10,
                    "max_long_term_memories": 10,
                    "similarity_threshold": 0.7,
                    "include_identity": True,
                }
            ]
        }
    }
