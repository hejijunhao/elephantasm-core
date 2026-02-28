"""
Light Sleep Phase - Algorithmic Memory Processing

Fast, deterministic operations on all memories (no LLM calls):
- Decay score updates based on time elapsed
- State transitions (ACTIVE → DECAYING → ARCHIVED)
- Flagging candidates for Deep Sleep review
- Merge candidate detection via pgVector embedding similarity
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select, and_

from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import DreamPhase, DreamSession
from app.models.database.memories import Memory, MemoryState
from app.services.dreamer.config import DreamerConfig
from app.services.dreamer.gather import DreamContext

logger = logging.getLogger(__name__)


@dataclass
class LightSleepResults:
    """Results from Light Sleep phase."""

    memories_processed: int = 0
    """Total memories examined."""

    decay_updates: int = 0
    """Number of decay_score updates."""

    state_transitions: int = 0
    """Number of state changes (ACTIVE → DECAYING → ARCHIVED)."""

    merge_candidates: list[list[UUID]] = field(default_factory=list)
    """Groups of memory IDs that may be duplicates (for Deep Sleep review)."""

    review_candidates: set[UUID] = field(default_factory=set)
    """Individual memory IDs flagged for Deep Sleep review."""


def run_light_sleep(
    session: Session,
    dream_session: DreamSession,
    context: DreamContext,
    config: DreamerConfig,
) -> LightSleepResults:
    """
    Execute Light Sleep phase.

    Algorithmic operations (no LLM):
    1. Update decay scores based on time elapsed
    2. Transition stale memories (ACTIVE → DECAYING → ARCHIVED)
    3. Flag duplicate/similar memories for merge review
    4. Flag low-confidence memories for Deep Sleep review

    Args:
        session: Database session
        dream_session: Parent dream session
        context: Gathered context from gather phase
        config: Dreamer configuration

    Returns:
        LightSleepResults with metrics and flagged candidates
    """
    results = LightSleepResults()
    results.memories_processed = len(context.memories)

    if not context.memories:
        logger.info(f"No memories to process for anima {context.anima_id}")
        return results

    # 1. Update decay scores
    results.decay_updates = _update_decay_scores(
        session, dream_session, context.memories, config
    )

    # 2. Transition stale memories
    results.state_transitions = _transition_stale_memories(
        session, dream_session, context.memories, config
    )

    # 3. Flag merge candidates (embedding similarity via pgVector)
    results.merge_candidates = _find_merge_candidates(
        session, context.memories, config
    )

    # 4. Flag low-confidence memories for review
    results.review_candidates = _find_review_candidates(context.memories, config)

    # 5. Add recent memories to review candidates (priority review)
    for memory in context.recent_memories:
        results.review_candidates.add(memory.id)

    logger.info(
        f"Light Sleep complete: {results.decay_updates} decay updates, "
        f"{results.state_transitions} transitions, "
        f"{len(results.merge_candidates)} merge groups, "
        f"{len(results.review_candidates)} review candidates"
    )

    return results


def _update_decay_scores(
    session: Session,
    dream_session: DreamSession,
    memories: list[Memory],
    config: DreamerConfig,
) -> int:
    """
    Update decay scores based on time since last update.

    Decay formula: decay_score = min(1.0, age_days / half_life_days)
    - At half_life_days, decay_score = 0.5
    - At 2*half_life_days, decay_score = 1.0 (capped)

    Only updates ACTIVE memories with significant change (>0.01).
    """
    updated = 0
    now = datetime.now(timezone.utc)

    for memory in memories:
        if memory.state != MemoryState.ACTIVE:
            continue

        # Calculate age in days
        # Use updated_at as "last touched" indicator
        last_touched = memory.updated_at
        if last_touched.tzinfo is None:
            # Handle naive datetime (shouldn't happen but be defensive)
            last_touched = last_touched.replace(tzinfo=timezone.utc)

        age_delta = now - last_touched
        age_days = age_delta.total_seconds() / (24 * 3600)

        # Calculate new decay score
        new_decay = min(1.0, age_days / config.decay_half_life_days)
        old_decay = memory.decay_score or 0.0

        # Only update if significant change
        if abs(old_decay - new_decay) > 0.01:
            DreamerOperations.update_memory(
                session,
                dream_session=dream_session,
                memory_id=memory.id,
                updates={"decay_score": new_decay},
                phase=DreamPhase.LIGHT_SLEEP,
                reasoning=None,  # Algorithmic, no reasoning needed
            )
            updated += 1

    return updated


def _transition_stale_memories(
    session: Session,
    dream_session: DreamSession,
    memories: list[Memory],
    config: DreamerConfig,
) -> int:
    """
    Transition memories based on staleness criteria.

    Transitions:
    - ACTIVE → DECAYING: High decay + low importance
    - DECAYING → ARCHIVED: Very high decay
    """
    transitioned = 0

    for memory in memories:
        new_state: MemoryState | None = None

        decay = memory.decay_score or 0.0
        importance = memory.importance or 0.5

        # ACTIVE → DECAYING: High decay + low importance
        if memory.state == MemoryState.ACTIVE:
            if decay > config.decay_threshold and importance < config.importance_floor:
                new_state = MemoryState.DECAYING
                logger.debug(
                    f"Memory {memory.id} transitioning ACTIVE → DECAYING "
                    f"(decay={decay:.2f}, importance={importance:.2f})"
                )

        # DECAYING → ARCHIVED: Very high decay
        elif memory.state == MemoryState.DECAYING:
            if decay > config.archive_threshold:
                new_state = MemoryState.ARCHIVED
                logger.debug(
                    f"Memory {memory.id} transitioning DECAYING → ARCHIVED "
                    f"(decay={decay:.2f})"
                )

        if new_state:
            DreamerOperations.archive_memory(
                session,
                dream_session=dream_session,
                memory_id=memory.id,
                new_state=new_state,
                phase=DreamPhase.LIGHT_SLEEP,
                reasoning=None,  # Algorithmic, no reasoning
            )
            transitioned += 1

    return transitioned


def _find_merge_candidates(
    session: Session,
    memories: list[Memory],
    config: DreamerConfig,
) -> list[list[UUID]]:
    """
    Find groups of memories that might be duplicates/redundant.

    Primary: pgVector embedding cosine distance for semantic matching.
    Fallback: Jaccard word similarity for memories without embeddings.

    Returns:
        List of memory ID groups, each group potentially redundant.
    """
    candidates: list[list[UUID]] = []
    processed: set[UUID] = set()

    # Filter to ACTIVE memories only
    active_memories = [m for m in memories if m.state == MemoryState.ACTIVE]

    for m1 in active_memories:
        if m1.id in processed:
            continue

        group = [m1.id]

        # Primary: Embedding similarity via pgVector
        if m1.embedding is not None:
            similar_ids = _find_similar_by_embedding(
                session,
                m1,
                active_memories,
                processed,
                config.embedding_similarity_threshold,
            )
            for similar_id in similar_ids:
                group.append(similar_id)
                processed.add(similar_id)

        else:
            # Fallback: Jaccard word similarity
            similar_ids = _find_similar_by_jaccard(
                m1, active_memories, processed, config.jaccard_fallback_threshold
            )
            for similar_id in similar_ids:
                group.append(similar_id)
                processed.add(similar_id)

        if len(group) > 1:
            candidates.append(group)
            processed.add(m1.id)

    return candidates


def _find_similar_by_embedding(
    session: Session,
    source_memory: Memory,
    candidate_memories: list[Memory],
    exclude_ids: set[UUID],
    threshold: float,
) -> list[UUID]:
    """
    Find memories similar to source via pgVector cosine distance.

    Args:
        session: Database session
        source_memory: Memory to compare against
        candidate_memories: Pool of memories to search
        exclude_ids: IDs already processed (skip)
        threshold: Cosine distance threshold (lower = more similar)

    Returns:
        List of similar memory IDs
    """
    if source_memory.embedding is None:
        return []

    # Get IDs to search (exclude already processed)
    search_ids = [
        m.id for m in candidate_memories
        if m.id != source_memory.id
        and m.id not in exclude_ids
        and m.embedding is not None
    ]

    if not search_ids:
        return []

    # Query for similar memories via pgVector
    # cosine_distance: 0 = identical, 2 = opposite
    result = session.execute(
        select(Memory.id)
        .where(
            and_(
                Memory.id.in_(search_ids),
                Memory.embedding.isnot(None),
                Memory.embedding.cosine_distance(source_memory.embedding) < threshold,
            )
        )
    )

    return [row[0] for row in result.all()]


def _find_similar_by_jaccard(
    source_memory: Memory,
    candidate_memories: list[Memory],
    exclude_ids: set[UUID],
    threshold: float,
) -> list[UUID]:
    """
    Find memories similar to source via Jaccard word similarity.

    Fallback for memories without embeddings.
    """
    if not source_memory.summary:
        return []

    words1 = set(source_memory.summary.lower().split())
    similar_ids: list[UUID] = []

    for m2 in candidate_memories:
        if m2.id == source_memory.id or m2.id in exclude_ids:
            continue
        if m2.embedding is not None:
            continue  # Will be handled by embedding path
        if not m2.summary:
            continue

        words2 = set(m2.summary.lower().split())
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        if union > 0:
            similarity = intersection / union
            if similarity > threshold:
                similar_ids.append(m2.id)

    return similar_ids


def _find_review_candidates(
    memories: list[Memory],
    config: DreamerConfig,
) -> set[UUID]:
    """
    Find memories that need Deep Sleep review.

    Criteria:
    - Low confidence (uncertain memories)
    - Very short summary (might need expansion)
    """
    candidates: set[UUID] = set()

    for memory in memories:
        if memory.state != MemoryState.ACTIVE:
            continue

        # Low confidence = needs review
        confidence = memory.confidence or 0.5
        if confidence < config.confidence_review_threshold:
            candidates.add(memory.id)
            continue

        # Very short summary = might need expansion
        if memory.summary and len(memory.summary) < config.min_summary_length:
            candidates.add(memory.id)

    return candidates
