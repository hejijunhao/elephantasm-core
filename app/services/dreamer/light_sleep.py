"""
Light Sleep Phase - Algorithmic Memory Processing

Fast, deterministic operations on all memories (no LLM calls):
- Decay score updates based on time elapsed
- State transitions (ACTIVE → DECAYING → ARCHIVED)
- Cluster detection via pgVector similarity graph + Union-Find
- Flagging candidates for Deep Sleep review
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlmodel import Session

from app.algos.mem_scoring.decay import compute_decay_score
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

    clusters: list[list[UUID]] = field(default_factory=list)
    """Clusters of related memory IDs (connected components from similarity graph).
    Sorted by size descending. Singletons excluded. Min cluster size is 2."""

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

    # 3. Build similarity clusters (connected components via pgVector + Jaccard)
    results.clusters = _build_similarity_clusters(
        session, context.memories, config
    )

    # 4. Flag low-confidence memories for review
    results.review_candidates = _find_review_candidates(context.memories, config)

    # 5. Add recent memories to review candidates (priority review)
    for memory in context.recent_memories:
        results.review_candidates.add(memory.id)

    cluster_sizes = [len(c) for c in results.clusters]
    logger.info(
        f"Light Sleep complete: {results.decay_updates} decay updates, "
        f"{results.state_transitions} transitions, "
        f"{len(results.clusters)} clusters (sizes: {cluster_sizes}), "
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
    Update decay scores using exponential decay with spaced repetition.

    Uses compute_decay_score() from algos/mem_scoring/decay.py:
    - Exponential decay: 1 - e^(-ln(2)/hl * age_days)
    - Spaced repetition: effective_hl = base * (1.5^access_count)
    - Reference time: last_accessed or created_at

    Only updates ACTIVE memories with significant change (>0.01).
    """
    updated = 0

    for memory in memories:
        if memory.state != MemoryState.ACTIVE:
            continue

        new_decay = compute_decay_score(
            memory_time=memory.created_at,
            last_accessed=None,  # TODO: add access tracking
            access_count=0,  # TODO: add access tracking
            base_half_life_days=config.decay_half_life_days,
        )
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


def _build_similarity_clusters(
    session: Session,
    memories: list[Memory],
    config: DreamerConfig,
) -> list[list[UUID]]:
    """
    Build similarity graph and find connected components via Union-Find.

    1. pgVector self-join for memories with embeddings (cosine distance)
    2. Jaccard fallback for memories without embeddings
    3. Union-Find groups edges into connected components
    4. Large clusters (>threshold) split into denser sub-clusters

    Returns:
        List of clusters, each a list of memory IDs. Singletons excluded.
        Sorted by size descending (largest clusters first).
    """
    active = [m for m in memories if m.state == MemoryState.ACTIVE]
    if len(active) < 2:
        return []

    # Split into memories with/without embeddings
    with_embeddings = [m for m in active if m.embedding is not None]
    without_embeddings = [m for m in active if m.embedding is None]

    # Collect all similarity edges
    edges = _get_similar_pairs(
        session, with_embeddings, config.cluster_similarity_threshold
    )
    edges.extend(
        _get_jaccard_pairs(without_embeddings, config.jaccard_fallback_threshold)
    )

    if not edges:
        return []

    # Build connected components via Union-Find
    components = _union_find_clusters([(a, b) for a, b, _dist in edges])

    # Filter singletons, sort by size descending
    clusters = [
        list(members)
        for members in components.values()
        if len(members) >= 2
    ]
    clusters.sort(key=len, reverse=True)

    # Split large clusters into denser sub-clusters
    if config.large_cluster_threshold > 0:
        clusters = _split_large_clusters(clusters, edges, config)

    return clusters


def _union_find_clusters(
    edges: list[tuple[UUID, UUID]],
) -> dict[UUID, set[UUID]]:
    """Group nodes into connected components via Union-Find with path compression."""
    parent: dict[UUID, UUID] = {}

    def find(x: UUID) -> UUID:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])  # path compression
            x = parent[x]
        return x

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in edges:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        union(a, b)

    # Group by root
    groups: dict[UUID, set[UUID]] = {}
    for node in parent:
        root = find(node)
        groups.setdefault(root, set()).add(node)

    return groups


def _split_large_clusters(
    clusters: list[list[UUID]],
    edges: list[tuple[UUID, UUID, float]],
    config: DreamerConfig,
) -> list[list[UUID]]:
    """
    Split clusters exceeding large_cluster_threshold into denser sub-clusters.

    Uses a tighter distance threshold (0.5× original) to find natural
    sub-groups within the oversized component.
    """
    result: list[list[UUID]] = []

    for cluster in clusters:
        if len(cluster) <= config.large_cluster_threshold:
            result.append(cluster)
            continue

        # Filter edges to only those within this cluster
        cluster_set = set(cluster)
        tighter_threshold = config.cluster_similarity_threshold * 0.5
        inner_edges = [
            (a, b)
            for a, b, dist in edges
            if a in cluster_set and b in cluster_set and dist < tighter_threshold
        ]

        if not inner_edges:
            # No edges at tighter threshold — keep original cluster
            result.append(cluster)
            continue

        # Re-cluster with tighter edges
        sub_components = _union_find_clusters(inner_edges)
        sub_clusters = [
            list(members)
            for members in sub_components.values()
            if len(members) >= 2
        ]
        sub_clusters.sort(key=len, reverse=True)

        if sub_clusters:
            result.extend(sub_clusters)
        else:
            result.append(cluster)

    result.sort(key=len, reverse=True)
    return result


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
