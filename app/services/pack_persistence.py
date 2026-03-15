"""
Pack persistence service.

Provides:
- build_pack_data(): Converts compiled pack to dict for MemoryPack model creation.
- persist_pack_async(): Fire-and-forget background persistence after HTTP response.
"""

import logging
from typing import Optional
from uuid import UUID

from app.core.database import get_db_with_rls_context
from app.domain.memory_pack_operations import MemoryPackOperations
from app.models.database.memory_pack import MemoryPack
from app.models.dto.retrieval import RetrievalConfig

logger = logging.getLogger(__name__)

# Retention policy: max packs per anima
MAX_PACKS_PER_ANIMA = 100


def build_pack_data(
    pack,
    config: RetrievalConfig,
    preset_name: Optional[str] = None
) -> dict:
    """
    Convert compiled pack to dict for MemoryPack model creation.

    Serializes all pack data into a format suitable for MemoryPack(**data).
    Used by both fire-and-forget persistence and inline persistence paths.
    """
    return {
        "anima_id": config.anima_id,
        "query": config.query,
        "preset_name": preset_name,
        "session_memory_count": len(pack.session_memories),
        "pending_event_count": len(pack.pending_events),
        "knowledge_count": len(pack.knowledge),
        "long_term_memory_count": len(pack.long_term_memories),
        "has_identity": pack.identity is not None,
        "has_temporal_context": pack.temporal_context is not None,
        "token_count": pack.token_count,
        "max_tokens": config.max_tokens or 4000,
        "content": {
            "context": pack.to_prompt_context(),
            "pending_events": [
                {
                    "id": str(pe.event.id),
                    "content": (pe.event.content or "")[:500],
                    "summary": pe.event.summary,
                    "event_type": pe.event.event_type.value if hasattr(pe.event.event_type, 'value') else str(pe.event.event_type),
                    "role": pe.event.role,
                    "author": pe.event.author,
                    "occurred_at": (pe.event.occurred_at or pe.event.created_at).isoformat(),
                }
                for pe in pack.pending_events
            ],
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


def persist_pack_async(pack_data: dict, anima_id: UUID, user_id: Optional[UUID] = None) -> None:
    """
    Fire-and-forget pack persistence.

    Runs in FastAPI's background thread pool after response is sent.
    Handles its own session lifecycle and error recovery.

    Args:
        pack_data: Dict with MemoryPack fields (from build_pack_data)
        anima_id: Anima UUID for retention policy enforcement
        user_id: User UUID for RLS context (required for multi-tenant isolation)

    Note:
        - Uses RLS-enabled session for multi-tenant isolation
        - Commits independently of main request
        - Errors are logged but don't affect the response
        - Retention cleanup runs in same transaction
    """
    try:
        with get_db_with_rls_context(user_id) as session:
            # Create pack from data
            pack = MemoryPack(**pack_data)
            saved = MemoryPackOperations.create(session, pack)

            # Enforce retention (delete old packs beyond limit)
            deleted = MemoryPackOperations.enforce_retention(
                session,
                anima_id=anima_id,
                max_packs=MAX_PACKS_PER_ANIMA
            )

            # Commit handled by context manager

            if deleted > 0:
                logger.debug(f"Pack {saved.id} persisted, {deleted} old packs pruned")
            else:
                logger.debug(f"Pack {saved.id} persisted")

    except Exception as e:
        logger.error(f"Background pack persistence failed: {e}")
