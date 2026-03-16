"""
Reflection Phase - Algorithmic Knowledge Processing

Lighter than Dreamer's Light Sleep — NO decay, NO state transitions.
Two operations only:
1. Cluster detection via pgVector similarity graph + topic grouping + Union-Find
2. Flagging candidates for Contemplation review
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlmodel import Session

from app.models.database.knowledge import Knowledge
from app.services.meditator.config import MeditatorConfig
from app.services.meditator.gather import MeditationContext

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResults:
    """Results from Reflection phase."""

    knowledge_processed: int = 0
    """Total knowledge items examined."""

    clusters: list[list[UUID]] = field(default_factory=list)
    """Clusters of related knowledge IDs (connected components from similarity graph).
    Sorted by size descending. Singletons excluded. Min cluster size is 2."""

    review_candidates: set[UUID] = field(default_factory=set)
    """Individual knowledge IDs flagged for Contemplation review."""


def run_reflection(
    session: Session,
    context: MeditationContext,
    config: MeditatorConfig,
) -> ReflectionResults:
    """
    Execute Reflection phase (algorithmic, no LLM).

    1. Build similarity clusters (pgVector + topic grouping + Jaccard)
    2. Flag review candidates (low confidence, short content, recent)

    Args:
        session: Database session
        context: Gathered context from gather phase
        config: Meditator configuration

    Returns:
        ReflectionResults with clusters and flagged candidates
    """
    results = ReflectionResults()
    results.knowledge_processed = len(context.knowledge)

    if not context.knowledge:
        logger.info(f"No knowledge to process for anima {context.anima_id}")
        return results

    # 1. Build similarity clusters
    results.clusters = _build_similarity_clusters(
        session, context.knowledge, config
    )

    # 2. Flag review candidates
    results.review_candidates = _find_review_candidates(context.knowledge, config)

    # 3. Add recent knowledge to review candidates (priority review)
    for k in context.recent_knowledge:
        results.review_candidates.add(k.id)

    cluster_sizes = [len(c) for c in results.clusters]
    logger.info(
        f"Reflection complete: "
        f"{len(results.clusters)} clusters (sizes: {cluster_sizes}), "
        f"{len(results.review_candidates)} review candidates"
    )

    return results


def _build_similarity_clusters(
    session: Session,
    knowledge: list[Knowledge],
    config: MeditatorConfig,
) -> list[list[UUID]]:
    """
    Build similarity graph and find connected components via Union-Find.

    Three edge sources:
    1. pgVector cosine distance (semantic similarity)
    2. Jaccard word overlap fallback (items without embeddings)
    3. Exact topic match (automatic edge between items sharing topic)

    Returns:
        List of clusters, each a list of knowledge IDs. Singletons excluded.
        Sorted by size descending.
    """
    if len(knowledge) < 2:
        return []

    with_embeddings = [k for k in knowledge if k.embedding is not None]
    without_embeddings = [k for k in knowledge if k.embedding is None]

    # Collect all similarity edges
    edges = _get_similar_pairs(
        session, with_embeddings, config.cluster_similarity_threshold
    )
    edges.extend(
        _get_jaccard_pairs(without_embeddings, config.jaccard_fallback_threshold)
    )
    edges.extend(
        _get_topic_pairs(knowledge)
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

    # Split large clusters
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
            parent[x] = parent.get(parent[x], parent[x])
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

    groups: dict[UUID, set[UUID]] = {}
    for node in parent:
        root = find(node)
        groups.setdefault(root, set()).add(node)

    return groups


def _split_large_clusters(
    clusters: list[list[UUID]],
    edges: list[tuple[UUID, UUID, float]],
    config: MeditatorConfig,
) -> list[list[UUID]]:
    """Split clusters exceeding large_cluster_threshold using tighter distance."""
    result: list[list[UUID]] = []

    for cluster in clusters:
        if len(cluster) <= config.large_cluster_threshold:
            result.append(cluster)
            continue

        cluster_set = set(cluster)
        tighter_threshold = config.cluster_similarity_threshold * 0.5
        inner_edges = [
            (a, b)
            for a, b, dist in edges
            if a in cluster_set and b in cluster_set and dist < tighter_threshold
        ]

        if not inner_edges:
            result.append(cluster)
            continue

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
    knowledge: list[Knowledge],
    threshold: float,
) -> list[tuple[UUID, UUID, float]]:
    """Find all knowledge pairs below cosine distance threshold via pgVector self-join."""
    if len(knowledge) < 2:
        return []

    from sqlalchemy import text

    knowledge_ids = [k.id for k in knowledge]

    result = session.execute(
        text("""
            SELECT k1.id AS id1, k2.id AS id2,
                   (k1.embedding <=> k2.embedding) AS distance
            FROM knowledge k1
            JOIN knowledge k2 ON k1.id < k2.id
            WHERE k1.id = ANY(:ids)
              AND k2.id = ANY(:ids)
              AND k1.embedding IS NOT NULL
              AND k2.embedding IS NOT NULL
              AND (k1.embedding <=> k2.embedding) < :threshold
        """),
        {"ids": knowledge_ids, "threshold": threshold},
    )

    return [(row.id1, row.id2, row.distance) for row in result.all()]


def _get_jaccard_pairs(
    knowledge: list[Knowledge],
    threshold: float,
) -> list[tuple[UUID, UUID, float]]:
    """Find knowledge pairs with Jaccard word similarity above threshold."""
    pairs: list[tuple[UUID, UUID, float]] = []
    word_sets = {}
    for k in knowledge:
        text = (k.content or "") + " " + (k.summary or "")
        if text.strip():
            word_sets[k.id] = set(text.lower().split())

    ids = list(word_sets.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            w1, w2 = word_sets[ids[i]], word_sets[ids[j]]
            union = len(w1 | w2)
            if union > 0:
                similarity = len(w1 & w2) / union
                if similarity > threshold:
                    pairs.append((ids[i], ids[j], 1.0 - similarity))

    return pairs


def _get_topic_pairs(
    knowledge: list[Knowledge],
) -> list[tuple[UUID, UUID, float]]:
    """
    Create edges between knowledge items with the exact same topic.

    Topic-based clustering layered on top of semantic clustering.
    Distance set to 0.15 — above the tighter split threshold (0.125)
    so mega-clusters from shared topics can still be split.
    """
    pairs: list[tuple[UUID, UUID, float]] = []
    by_topic: dict[str, list[UUID]] = {}

    for k in knowledge:
        if k.topic:
            by_topic.setdefault(k.topic.lower().strip(), []).append(k.id)

    for topic_ids in by_topic.values():
        if len(topic_ids) < 2:
            continue
        for i in range(len(topic_ids)):
            for j in range(i + 1, len(topic_ids)):
                pairs.append((topic_ids[i], topic_ids[j], 0.15))

    return pairs


def _find_review_candidates(
    knowledge: list[Knowledge],
    config: MeditatorConfig,
) -> set[UUID]:
    """
    Find knowledge items that need Contemplation review.

    Criteria:
    - Low confidence (uncertain knowledge)
    - Very short content (might need expansion)
    """
    candidates: set[UUID] = set()

    for k in knowledge:
        confidence = k.confidence or 0.5
        if confidence < config.confidence_review_threshold:
            candidates.add(k.id)
            continue

        if k.content and len(k.content) < config.min_content_length:
            candidates.add(k.id)

    return candidates
