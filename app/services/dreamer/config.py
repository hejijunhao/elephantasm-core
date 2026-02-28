"""
Dreamer Configuration

Sensible defaults for memory curation parameters.
LLM settings are SEPARATE from Anima's synthesis config — keeps Dreamer modular.
Future: per-Anima overrides via Settings page.
"""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class DreamerConfig:
    """
    Configuration for the Dreamer service.

    All thresholds use 0.0-1.0 scale unless otherwise noted.
    Embedding similarity uses cosine distance (0 = identical, 2 = opposite).
    """

    # ─────────────────────────────────────────────────────────────
    # Decay Scoring
    # ─────────────────────────────────────────────────────────────
    decay_half_life_days: float = 30.0
    """Days until decay_score reaches 0.5. Lower = faster decay."""

    decay_threshold: float = 0.7
    """Decay score above which ACTIVE memories may transition to DECAYING."""

    archive_threshold: float = 0.9
    """Decay score above which DECAYING memories transition to ARCHIVED."""

    # ─────────────────────────────────────────────────────────────
    # Importance Thresholds
    # ─────────────────────────────────────────────────────────────
    importance_floor: float = 0.3
    """Memories below this importance (combined with high decay) become DECAYING."""

    # ─────────────────────────────────────────────────────────────
    # Review Thresholds (for Deep Sleep candidates)
    # ─────────────────────────────────────────────────────────────
    confidence_review_threshold: float = 0.4
    """Memories with confidence below this get flagged for LLM review."""

    min_summary_length: int = 20
    """Summaries shorter than this get flagged for potential expansion."""

    # ─────────────────────────────────────────────────────────────
    # Merge Detection
    # ─────────────────────────────────────────────────────────────
    embedding_similarity_threshold: float = 0.3
    """
    Cosine distance threshold for merge candidates.
    Lower = more similar required. 0 = identical, 2 = opposite.
    0.3 catches semantically similar memories without false positives.
    """

    jaccard_fallback_threshold: float = 0.6
    """
    Word overlap threshold for memories without embeddings.
    Higher = more overlap required. Range: 0.0-1.0.
    """

    # ─────────────────────────────────────────────────────────────
    # LLM Settings (separate from synthesis config)
    # ─────────────────────────────────────────────────────────────
    llm_provider: str = "openai"
    """LLM provider for Deep Sleep curation. Options: openai, anthropic."""

    llm_model: str = "gpt-4o-mini"
    """Model for curation decisions. Default: fast/cheap for batch processing."""

    llm_temperature: float = 0.3
    """Low temperature for consistent, deterministic curation decisions."""

    curation_batch_size: int = 10
    """Number of memories to process per LLM call in Deep Sleep."""

    # ─────────────────────────────────────────────────────────────
    # Embedding Regeneration
    # ─────────────────────────────────────────────────────────────
    regenerate_embeddings: bool = True
    """Whether to regenerate embeddings after merge/split/summary-update."""

    embedding_model: str = "text-embedding-3-small"
    """OpenAI embedding model. Matches existing Memory embeddings."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize config for storage in dream_sessions.config_snapshot."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DreamerConfig":
        """Reconstruct config from stored snapshot."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
