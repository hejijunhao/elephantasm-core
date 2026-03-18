"""
Unified Query API — "Grep the Brain"

Single cross-source endpoint for agent consumption.
Searches memories + knowledge + identity in one call,
returns both structured results and pre-formatted context.

Pattern: Async route, sync domain operations.
"""

from datetime import timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.domain.identity_operations import IdentityOperations
from app.domain.knowledge_retrieval import KnowledgeRetrieval
from app.domain.memory_operations import MemoryOperations
from app.models.database.memories import MemoryState
from app.models.dto.query import (
    IdentityContextResponse,
    QueryRequest,
    QueryResponse,
    QueryResult,
)

router = APIRouter(prefix="/query")


@router.post("", response_model=QueryResponse)
async def unified_query(
    request: QueryRequest,
    db: Session = Depends(get_db_with_rls),
) -> QueryResponse:
    """
    Cross-source brain search. One query, ranked results from
    memories + knowledge + identity. Returns both structured
    results and a pre-formatted context string for prompt injection.
    """
    from app.services.embeddings import get_embedding_provider

    # 1. Embed query once
    provider = get_embedding_provider()
    query_embedding = provider.embed_text(request.query)

    exclude_set = set(request.exclude_ids) if request.exclude_ids else set()
    results: List[QueryResult] = []

    # 2. Search memories
    if "memories" in request.sources:
        memory_results = MemoryOperations.search_similar(
            session=db,
            anima_id=request.anima_id,
            query_embedding=query_embedding,
            limit=request.limit * 3,
            threshold=request.threshold,
            state=MemoryState.ACTIVE,
        )
        for memory, similarity in memory_results:
            if memory.id in exclude_set:
                continue
            if not _passes_time_filter(
                request, memory.time_start, memory.time_end
            ):
                continue
            results.append(
                QueryResult(
                    id=memory.id,
                    source="memory",
                    content=memory.summary or memory.content or "",
                    similarity=round(similarity, 4),
                    importance=memory.importance,
                    confidence=memory.confidence,
                    time_start=memory.time_start,
                )
            )

    # 3. Search knowledge
    if "knowledge" in request.sources:
        knowledge_results = KnowledgeRetrieval.search_similar(
            session=db,
            anima_id=request.anima_id,
            query_embedding=query_embedding,
            limit=request.limit * 3,
            threshold=request.threshold,
        )
        for knowledge, similarity in knowledge_results:
            if knowledge.id in exclude_set:
                continue
            if not _passes_time_filter(
                request, knowledge.created_at, None
            ):
                continue
            results.append(
                QueryResult(
                    id=knowledge.id,
                    source="knowledge",
                    content=knowledge.content or "",
                    similarity=round(similarity, 4),
                    type=knowledge.knowledge_type.value
                    if knowledge.knowledge_type
                    else None,
                    topic=knowledge.topic,
                    confidence=knowledge.confidence,
                )
            )

    # 4. Sort by similarity descending
    results.sort(key=lambda r: r.similarity, reverse=True)

    # 5. Fetch identity
    identity_context = None
    if "identity" in request.sources:
        identity = IdentityOperations.get_by_anima_id(db, request.anima_id)
        if identity:
            identity_context = IdentityContextResponse(
                personality_type=identity.personality_type.value
                if identity.personality_type
                else None,
                communication_style=identity.communication_style,
                self_reflection=identity.self_ if identity.self_ else None,
            )

    # 6. Apply token budget + limit
    identity_tokens = 150 if identity_context else 0
    remaining_budget = request.max_tokens - identity_tokens

    trimmed: List[QueryResult] = []
    tokens_used = 0
    for r in results:
        if len(trimmed) >= request.limit:
            break
        est = len(r.content) // 4
        if tokens_used + est > remaining_budget:
            break
        trimmed.append(r)
        tokens_used += est

    # 7. Format context string
    context = _format_context(trimmed, identity_context)
    token_estimate = tokens_used + identity_tokens

    return QueryResponse(
        results=trimmed,
        identity_context=identity_context,
        context=context,
        token_estimate=token_estimate,
    )


def _passes_time_filter(
    request: QueryRequest,
    start_time,
    end_time,
) -> bool:
    """Check if a result passes the time_range filter."""
    if not request.time_range:
        return True

    # Use start_time as the primary timestamp
    ts = start_time or end_time
    if ts is None:
        return True

    # Ensure timezone-aware comparison
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    if request.time_range.after:
        after = request.time_range.after
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
        if ts < after:
            return False

    if request.time_range.before:
        before = request.time_range.before
        if before.tzinfo is None:
            before = before.replace(tzinfo=timezone.utc)
        if ts > before:
            return False

    return True


def _format_context(
    results: List[QueryResult],
    identity: IdentityContextResponse | None,
) -> str:
    """Format results as injectable prompt context."""
    sections = []

    # Identity section
    if identity:
        parts = []
        if identity.personality_type:
            parts.append(f"Personality: {identity.personality_type}")
        if identity.communication_style:
            parts.append(f"Communication style: {identity.communication_style}")
        if parts:
            sections.append(f"## Identity\n" + "\n".join(parts))

    # Knowledge results
    knowledge_items = [r for r in results if r.source == "knowledge"]
    if knowledge_items:
        lines = []
        for k in knowledge_items:
            prefix = f"[{k.type}] " if k.type else ""
            topic = f"{k.topic}: " if k.topic else ""
            conf = f" (confidence: {k.confidence})" if k.confidence else ""
            lines.append(f"- {prefix}{topic}{k.content}{conf}")
        sections.append(f"## Knowledge\n" + "\n".join(lines))

    # Memory results
    memory_items = [r for r in results if r.source == "memory"]
    if memory_items:
        lines = []
        for m in memory_items:
            date = (
                m.time_start.strftime("%Y-%m-%d") if m.time_start else "Unknown"
            )
            imp = f" (importance: {m.importance})" if m.importance else ""
            lines.append(f"- [{date}] {m.content}{imp}")
        sections.append(f"## Memories\n" + "\n".join(lines))

    return "\n\n".join(sections)
