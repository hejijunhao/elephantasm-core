"""
Pack Compilation API Routes

Endpoints for compiling memory packs for LLM context injection.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.api.deps import RequireActionAllowed, SubscriptionContext
from app.services.memory_pack_compiler import MemoryPackCompiler
from app.services.pack_presets import get_preset
from app.services.pack_persistence import persist_pack_async
from app.models.dto.retrieval import RetrievalConfig
from app.models.dto.injection import (
    PackResponse,
    PackPreviewResponse,
    ScoredMemoryResponse,
    ScoredKnowledgeResponse,
    IdentitySummaryResponse,
    TemporalContextResponse,
)

router = APIRouter()


def _build_pack_data_for_persistence(
    pack,
    config: RetrievalConfig,
    preset_name: Optional[str] = None
) -> dict:
    """
    Convert compiled pack to dict for background persistence.

    Serializes all pack data into a format suitable for MemoryPack model.
    Called before scheduling background task.
    """
    return {
        "anima_id": config.anima_id,
        "query": config.query,
        "preset_name": preset_name,
        "session_memory_count": len(pack.session_memories),
        "knowledge_count": len(pack.knowledge),
        "long_term_memory_count": len(pack.long_term_memories),
        "has_identity": pack.identity is not None,
        "has_temporal_context": pack.temporal_context is not None,
        "token_count": pack.token_count,
        "max_tokens": config.max_tokens or 4000,
        "content": {
            "context": pack.to_prompt_context(),
            "session_memories": [
                {
                    "id": str(m.memory.id),
                    "summary": m.memory.summary,
                    "score": m.score,
                    "retrieval_reason": m.retrieval_reason.value,
                    "similarity": m.similarity,
                }
                for m in pack.session_memories
            ],
            "knowledge": [
                {
                    "id": str(k.knowledge.id),
                    "content": k.knowledge.content,
                    "knowledge_type": k.knowledge.knowledge_type.value,
                    "score": k.score,
                    "similarity": k.similarity,
                }
                for k in pack.knowledge
            ],
            "long_term_memories": [
                {
                    "id": str(m.memory.id),
                    "summary": m.memory.summary,
                    "score": m.score,
                    "retrieval_reason": m.retrieval_reason.value,
                    "similarity": m.similarity,
                }
                for m in pack.long_term_memories
            ],
            "identity": {
                "personality_type": pack.identity.personality_type,
                "communication_style": pack.identity.communication_style,
            } if pack.identity else None,
            "temporal_context": {
                "last_event_at": pack.temporal_context.last_event_at.isoformat(),
                "hours_ago": pack.temporal_context.hours_ago,
                "memory_summary": pack.temporal_context.memory_summary,
                "formatted": pack.temporal_context.formatted,
            } if pack.temporal_context else None,
            "config": {
                "anima_id": str(config.anima_id),
                "query": config.query,
                "max_tokens": config.max_tokens,
            },
        },
        "compiled_at": pack.compiled_at,
    }


def _build_pack_response(pack) -> PackResponse:
    """Convert MemoryPack to PackResponse."""
    return PackResponse(
        anima_id=pack.anima_id,
        query=pack.query,
        compiled_at=pack.compiled_at,
        token_count=pack.token_count,
        session_memory_count=len(pack.session_memories),
        knowledge_count=len(pack.knowledge),
        long_term_memory_count=len(pack.long_term_memories),
        has_identity=pack.identity is not None,
        has_temporal_context=pack.temporal_context is not None,
        context=pack.to_prompt_context(),
        identity=(
            IdentitySummaryResponse(
                personality_type=pack.identity.personality_type,
                communication_style=pack.identity.communication_style,
                self_reflection=pack.identity.self_reflection,
            )
            if pack.identity
            else None
        ),
        temporal_context=(
            TemporalContextResponse(
                last_event_at=pack.temporal_context.last_event_at,
                hours_ago=pack.temporal_context.hours_ago,
                memory_summary=pack.temporal_context.memory_summary,
                formatted=pack.temporal_context.formatted,
            )
            if pack.temporal_context
            else None
        ),
        session_memories=[
            ScoredMemoryResponse(
                id=m.memory.id,
                summary=m.memory.summary,
                score=m.score,
                retrieval_reason=m.retrieval_reason.value,
                similarity=m.similarity,
                time_start=m.memory.time_start,
                score_breakdown=m.score_breakdown,
            )
            for m in pack.session_memories
        ],
        knowledge=[
            ScoredKnowledgeResponse(
                id=k.knowledge.id,
                content=k.knowledge.content,
                knowledge_type=k.knowledge.knowledge_type.value,
                score=k.score,
                similarity=k.similarity,
            )
            for k in pack.knowledge
        ],
        long_term_memories=[
            ScoredMemoryResponse(
                id=m.memory.id,
                summary=m.memory.summary,
                score=m.score,
                retrieval_reason=m.retrieval_reason.value,
                similarity=m.similarity,
                time_start=m.memory.time_start,
                score_breakdown=m.score_breakdown,
            )
            for m in pack.long_term_memories
        ],
    )


@router.post("/compile", response_model=PackResponse)
async def compile_pack(
    config: RetrievalConfig,
    ctx: SubscriptionContext = Depends(RequireActionAllowed("pack_build")),
    db: Session = Depends(get_db_with_rls),
) -> PackResponse:
    """
    Compile a memory pack for LLM context injection.

    Assembles 4 layers:
    1. **Identity**: Static fetch (personality, communication style)
    2. **Session Memories**: Recent memories within session window (recency-scored)
    3. **Knowledge**: Semantic search results (confidence + similarity scored)
    4. **Long-term Memories**: Older memories with full 5-factor scoring

    Returns:
    - `context`: Formatted string ready for LLM injection
    - `token_count`: Estimated token usage
    - Detailed breakdown of all retrieved items with scores

    Subject to monthly pack build limit based on plan tier.
    """
    compiler = MemoryPackCompiler(db)
    pack = compiler.compile(config)
    return _build_pack_response(pack)


@router.post("/compile/preview", response_model=PackPreviewResponse)
async def preview_pack(
    config: RetrievalConfig,
    db: Session = Depends(get_db_with_rls),
) -> PackPreviewResponse:
    """
    Preview pack compilation without full content.

    Lighter response with just counts and top scores.
    Useful for UI previews or debugging retrieval configuration.
    """
    compiler = MemoryPackCompiler(db)
    pack = compiler.compile(config)

    return PackPreviewResponse(
        session_memory_count=len(pack.session_memories),
        knowledge_count=len(pack.knowledge),
        long_term_memory_count=len(pack.long_term_memories),
        has_identity=pack.identity is not None,
        has_temporal_context=pack.temporal_context is not None,
        token_count=pack.token_count,
        top_session_scores=[m.score for m in pack.session_memories[:3]],
        top_knowledge_scores=[k.score for k in pack.knowledge[:3]],
        top_longterm_scores=[m.score for m in pack.long_term_memories[:3]],
    )


@router.post("/compile/{preset_name}", response_model=PackResponse)
async def compile_pack_with_preset(
    preset_name: str,
    anima_id: UUID,
    query: Optional[str] = Query(default=None),
    persist: bool = Query(default=False, description="Persist pack to DB (fire-and-forget)"),
    background_tasks: BackgroundTasks = None,
    ctx: SubscriptionContext = Depends(RequireActionAllowed("pack_build")),
    db: Session = Depends(get_db_with_rls),
) -> PackResponse:
    """
    Compile a pack using a named preset.

    Available presets:
    - **conversational**: Fast, deterministic, good for quick chat.
      Low latency, predictable behavior. No LLM calls.
    - **self_determined**: LLM-adaptive, agent chooses retrieval strategy.
      Requires a query. Adds ~500-1000ms latency for LLM config generation.

    The preset provides pre-configured retrieval parameters optimized
    for the use case. You only need to provide anima_id and query.

    Args:
        persist: If True, saves pack to DB asynchronously (fire-and-forget).
                 Response returns immediately; persistence happens in background.
    """
    # Get preset config (may involve LLM call for self_determined)
    config = await get_preset(preset_name, anima_id, query)

    # Compile pack with preset config
    compiler = MemoryPackCompiler(db)
    pack = compiler.compile(config)

    # Build response first (before scheduling background task)
    response = _build_pack_response(pack)

    # Fire-and-forget persistence (non-blocking)
    if persist and background_tasks:
        pack_data = _build_pack_data_for_persistence(pack, config, preset_name)
        background_tasks.add_task(
            persist_pack_async,
            pack_data=pack_data,
            anima_id=anima_id,
            user_id=ctx.user_id,
        )

    return response
