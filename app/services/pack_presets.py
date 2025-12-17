"""
Pack Compilation Presets

Pre-configured retrieval profiles for common use cases.

Two presets for v1:
- `conversational`: Fully deterministic, fast, good for quick chat
- `self_determined`: LLM-adaptive, agent chooses retrieval strategy
"""

from typing import Optional
from uuid import UUID

from app.models.dto.retrieval import RetrievalConfig


# Fixed base config for self_determined preset (grounding)
SELF_DETERMINED_FIXED = {
    "include_identity": True,
    "include_temporal_awareness": True,
    "session_window_hours": 24,
    "max_session_memories": 5,
}


def get_conversational_preset(
    anima_id: UUID,
    query: Optional[str] = None,
) -> RetrievalConfig:
    """
    Fully deterministic preset for quick chat.

    No LLM calls — all params pre-set.
    Optimized for low latency and predictable behavior.

    Weights favor recency (conversation flow) over deep recall.
    """
    return RetrievalConfig(
        anima_id=anima_id,
        query=query,
        # Session configuration
        session_window_hours=4,
        max_session_memories=5,
        # Knowledge/long-term limits
        max_knowledge=3,
        max_long_term_memories=3,
        max_tokens=2000,
        # Weights: favor recency for conversation
        weight_recency=0.35,
        weight_similarity=0.30,
        weight_importance=0.20,
        weight_confidence=0.10,
        weight_decay=0.05,
        # Search settings
        similarity_threshold=0.7,
        include_identity=True,
        include_temporal_awareness=True,
    )


async def get_self_determined_preset(
    anima_id: UUID,
    query: str,
) -> RetrievalConfig:
    """
    LLM-adaptive preset. Fixed identity/session params,
    LLM chooses knowledge/long-term retrieval strategy.

    Requires a query (LLM needs context to decide).
    Adds ~500-1000ms latency for the LLM config generation call.

    Fixed parameters (grounding — always applied):
    - include_identity: true
    - session_window_hours: 24
    - max_session_memories: 5

    LLM-chosen parameters (adaptive):
    - knowledge_types
    - max_knowledge
    - max_long_term_memories
    - weight_* (scoring weights)
    - similarity_threshold
    - min_importance
    """
    if not query:
        raise ValueError("self_determined preset requires a query")

    # Lazy import to avoid circular dependency
    from app.services.llm import get_llm_client

    # Ask LLM what retrieval params it wants
    llm = get_llm_client()

    prompt = f'''Given this user query, determine optimal memory retrieval parameters.

Query: "{query}"

Return JSON with these fields:
- knowledge_types: list of types to retrieve (options: "FACT", "CONCEPT", "METHOD", "PRINCIPLE", "EXPERIENCE")
- max_knowledge: int 0-20 (how many knowledge items)
- max_long_term_memories: int 0-20 (how many long-term memories)
- weight_importance: float 0-1 (weight for memory importance)
- weight_similarity: float 0-1 (weight for semantic similarity)
- weight_recency: float 0-1 (weight for recency)
- similarity_threshold: float 0.5-0.9 (minimum similarity to include)
- min_importance: float 0-1 or null (minimum importance filter)

Consider:
- Factual questions → high knowledge, high similarity weight, types: FACT, CONCEPT
- Personal questions → preferences/beliefs, importance weighted, types: EXPERIENCE, PRINCIPLE
- Recent events → high recency weight, more long-term memories
- How-to questions → types: METHOD, higher max_knowledge
- Abstract/philosophical → lower threshold, broader recall, types: PRINCIPLE, CONCEPT

Respond with JSON only, no explanation.'''

    response = await llm.call(prompt)
    llm_params = llm.parse_json_response(response)

    # Parse knowledge_types if provided
    knowledge_types = None
    if llm_params.get("knowledge_types"):
        from app.models.database.knowledge import KnowledgeType

        try:
            knowledge_types = [
                KnowledgeType(kt) for kt in llm_params["knowledge_types"]
            ]
        except (ValueError, KeyError):
            # Invalid types, skip filtering
            knowledge_types = None

    # Merge fixed + LLM-chosen params
    return RetrievalConfig(
        anima_id=anima_id,
        query=query,
        # Fixed params (grounding)
        include_identity=SELF_DETERMINED_FIXED["include_identity"],
        include_temporal_awareness=SELF_DETERMINED_FIXED["include_temporal_awareness"],
        session_window_hours=SELF_DETERMINED_FIXED["session_window_hours"],
        max_session_memories=SELF_DETERMINED_FIXED["max_session_memories"],
        # LLM-chosen params (adaptive)
        knowledge_types=knowledge_types,
        max_knowledge=_clamp(llm_params.get("max_knowledge", 10), 0, 20),
        max_long_term_memories=_clamp(
            llm_params.get("max_long_term_memories", 10), 0, 20
        ),
        weight_importance=_clamp(llm_params.get("weight_importance", 0.25), 0, 1),
        weight_similarity=_clamp(llm_params.get("weight_similarity", 0.25), 0, 1),
        weight_recency=_clamp(llm_params.get("weight_recency", 0.20), 0, 1),
        weight_confidence=0.15,  # Keep stable
        weight_decay=0.15,  # Keep stable
        similarity_threshold=_clamp(
            llm_params.get("similarity_threshold", 0.7), 0.5, 0.9
        ),
        min_importance=llm_params.get("min_importance"),
        max_tokens=4000,  # Higher budget for self-determined
    )


async def get_preset(
    preset_name: str,
    anima_id: UUID,
    query: Optional[str] = None,
) -> RetrievalConfig:
    """
    Get a preset by name.

    Args:
        preset_name: "conversational" or "self_determined"
        anima_id: Anima to retrieve for
        query: Query for semantic search (required for self_determined)

    Returns:
        RetrievalConfig with preset values

    Raises:
        ValueError: If preset_name not recognized or query missing for self_determined
    """
    if preset_name == "conversational":
        return get_conversational_preset(anima_id, query)
    elif preset_name == "self_determined":
        if not query:
            raise ValueError("self_determined preset requires a query")
        return await get_self_determined_preset(anima_id, query)
    else:
        raise ValueError(
            f"Unknown preset: {preset_name}. Available: conversational, self_determined"
        )


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to range [min_val, max_val]."""
    if value is None:
        return min_val
    return max(min_val, min(max_val, float(value)))
