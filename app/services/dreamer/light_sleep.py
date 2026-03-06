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

from sqlmodel import Session

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
        # Use created_at (immutable) — updated_at resets on every decay_score
        # write due to TimestampMixin onupdate, creating a reset loop
        last_touched = memory.created_at
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
    Find PAIRS of memories that might be duplicates.

    Pairwise approach: finds the most similar pairs (not greedy groups),
    so each LLM merge call compares exactly 2 memories. Larger clusters
    converge naturally across multiple dream cycles.

    Returns:
        List of memory ID pairs, each pair potentially redundant.
    """
    active = [m for m in memories if m.state == MemoryState.ACTIVE]
    if len(active) < 2:
        return []

    # Split into memories with/without embeddings
    with_embeddings = [m for m in active if m.embedding is not None]
    without_embeddings = [m for m in active if m.embedding is None]

    # Primary: pgVector pairwise distances (single query)
    pairs = _get_similar_pairs(
        session, with_embeddings, config.embedding_similarity_threshold
    )

    # Fallback: Jaccard for memories without embeddings
    pairs.extend(
        _get_jaccard_pairs(without_embeddings, config.jaccard_fallback_threshold)
    )

    # Sort by distance (most similar first) and greedily select pairs
    pairs.sort(key=lambda p: p[2])
    claimed: set[UUID] = set()
    candidates: list[list[UUID]] = []

    for m1_id, m2_id, _distance in pairs:
        if m1_id in claimed or m2_id in claimed:
            continue
        candidates.append([m1_id, m2_id])
        claimed.add(m1_id)
        claimed.add(m2_id)
        if len(candidates) >= config.max_merge_groups:
            break

    return candidates


def _get_similar_pairs(
    session: Session,
    memories: list[Memory],
    threshold: float,
) -> list[tuple[UUID, UUID, float]]:
    """
    Find all memory pairs below cosine distance threshold via pgVector self-join.

    Uses raw SQL for the self-join — pgVector's <=> operator is cleanest this way.

    Returns:
        List of (id1, id2, distance) tuples, unordered.
    """
    if len(memories) < 2:
        return []

    from sqlalchemy import text

    memory_ids = [m.id for m in memories]

    result = session.execute(
        text("""
            SELECT m1.id AS id1, m2.id AS id2,
                   (m1.embedding <=> m2.embedding) AS distance
            FROM memories m1
            JOIN memories m2 ON m1.id < m2.id
            WHERE m1.id = ANY(:ids)
              AND m2.id = ANY(:ids)
              AND m1.embedding IS NOT NULL
              AND m2.embedding IS NOT NULL
              AND (m1.embedding <=> m2.embedding) < :threshold
        """),
        {"ids": memory_ids, "threshold": threshold},
    )

    return [(row.id1, row.id2, row.distance) for row in result.all()]


def _get_jaccard_pairs(
    memories: list[Memory],
    threshold: float,
) -> list[tuple[UUID, UUID, float]]:
    """
    Find memory pairs with Jaccard word similarity above threshold.

    Returns:
        List of (id1, id2, 1-similarity) tuples (lower = more similar).
    """
    pairs: list[tuple[UUID, UUID, float]] = []
    word_sets = {}
    for m in memories:
        if m.summary:
            word_sets[m.id] = set(m.summary.lower().split())

    ids = list(word_sets.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            w1, w2 = word_sets[ids[i]], word_sets[ids[j]]
            union = len(w1 | w2)
            if union > 0:
                similarity = len(w1 & w2) / union
                if similarity > threshold:
                    # Convert to distance (lower = more similar) for sorting
                    pairs.append((ids[i], ids[j], 1.0 - similarity))

    return pairs


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
