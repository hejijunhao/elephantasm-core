"""
Combined scoring algorithm.

Computes final retrieval score from all factors:
- importance: Memory's inherent importance (0-1)
- confidence: Certainty of memory accuracy (0-1)
- recency: Time-based freshness (0-1)
- decay: Forgetting curve factor (0-1, inverted in formula)
- similarity: Semantic similarity to query (0-1, optional)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ScoringWeights:
    """Configurable weights for score components."""

    importance: float = 0.25
    confidence: float = 0.15
    recency: float = 0.20
    decay: float = 0.15
    similarity: float = 0.25

    def normalize(self) -> "ScoringWeights":
        """Return new weights that sum to 1.0."""
        total = (
            self.importance
            + self.confidence
            + self.recency
            + self.decay
            + self.similarity
        )
        if total == 0:
            return ScoringWeights()  # Return defaults if all zero

        return ScoringWeights(
            importance=self.importance / total,
            confidence=self.confidence / total,
            recency=self.recency / total,
            decay=self.decay / total,
            similarity=self.similarity / total,
        )

    def normalize_without_similarity(self) -> "ScoringWeights":
        """Return weights normalized excluding similarity (for non-semantic retrieval)."""
        total = self.importance + self.confidence + self.recency + self.decay
        if total == 0:
            return ScoringWeights(similarity=0.0)

        return ScoringWeights(
            importance=self.importance / total,
            confidence=self.confidence / total,
            recency=self.recency / total,
            decay=self.decay / total,
            similarity=0.0,
        )


def compute_combined_score(
    importance: Optional[float],
    confidence: Optional[float],
    recency_score: float,
    decay_score: float,
    similarity: Optional[float],
    weights: ScoringWeights,
) -> float:
    """
    Compute final retrieval score from all factors.

    Args:
        importance: Memory importance (0-1), None defaults to 0.5
        confidence: Memory confidence (0-1), None defaults to 0.5
        recency_score: Pre-computed recency score (0-1)
        decay_score: Pre-computed decay score (0-1), will be inverted
        similarity: Semantic similarity (0-1), None if no query
        weights: Weight configuration

    Returns:
        Combined score from 0.0 to 1.0

    Formula:
        score = (importance × w_i) + (confidence × w_c) +
                (recency × w_r) + ((1 - decay) × w_d) +
                (similarity × w_s)

    Note: Decay is inverted because high decay = bad, low decay = good.
    """
    # Normalize weights based on whether we have similarity
    if similarity is not None:
        normalized = weights.normalize()
    else:
        normalized = weights.normalize_without_similarity()

    # Default None values to 0.5 (neutral)
    importance = importance if importance is not None else 0.5
    confidence = confidence if confidence is not None else 0.5

    # Compute weighted sum
    # Note: (1 - decay) because high decay is bad
    score = (
        importance * normalized.importance
        + confidence * normalized.confidence
        + recency_score * normalized.recency
        + (1 - decay_score) * normalized.decay
    )

    # Add similarity if available
    if similarity is not None:
        score += similarity * normalized.similarity

    return max(0.0, min(1.0, score))


def compute_knowledge_score(
    confidence: Optional[float],
    similarity: float,
) -> float:
    """
    Simplified scoring for Knowledge items.

    Knowledge doesn't use recency/decay (meant to be stable truths).
    Formula: (confidence × 0.5) + (similarity × 0.5)

    Args:
        confidence: Knowledge confidence (0-1)
        similarity: Semantic similarity to query (0-1)

    Returns:
        Score from 0.0 to 1.0
    """
    confidence = confidence if confidence is not None else 0.5
    return (confidence * 0.5) + (similarity * 0.5)
