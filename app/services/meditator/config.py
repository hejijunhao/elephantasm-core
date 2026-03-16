"""
Meditator Configuration

Sensible defaults for knowledge curation parameters.
LLM settings are SEPARATE from Anima's synthesis config — keeps Meditator modular.
"""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class MeditatorConfig:
    """
    Configuration for the Meditator service.

    All thresholds use 0.0-1.0 scale unless otherwise noted.
    Embedding similarity uses cosine distance (0 = identical, 2 = opposite).
    """

    # ─────────────────────────────────────────────────────────────
    # Trigger Threshold
    # ─────────────────────────────────────────────────────────────
    default_meditation_threshold: int = 10
    """Meditate after N knowledge syntheses (per-anima override in SynthesisConfig)."""

    # ─────────────────────────────────────────────────────────────
    # Cluster Detection
    # ─────────────────────────────────────────────────────────────
    cluster_similarity_threshold: float = 0.25
    """Cosine distance threshold for cluster edges. Tighter than Dreamer (0.3) —
    Knowledge is more specific than Memories."""

    jaccard_fallback_threshold: float = 0.5
    """Topic+content word overlap for items without embeddings."""

    large_cluster_threshold: int = 30
    """Clusters above this size are split. Smaller than Dreamer (50) —
    Knowledge clusters are denser."""

    # ─────────────────────────────────────────────────────────────
    # Review Thresholds
    # ─────────────────────────────────────────────────────────────
    min_content_length: int = 30
    """Very short content flagged for expansion."""

    confidence_review_threshold: float = 0.3
    """Below this → flagged for LLM review."""

    # ─────────────────────────────────────────────────────────────
    # LLM Settings (separate from synthesis + dreamer)
    # ─────────────────────────────────────────────────────────────
    merge_llm_provider: str = "openai"
    """LLM provider for pairwise merge decisions (2-item clusters). Fast/cheap."""

    merge_llm_model: str = "gpt-4o-mini"
    """Model for pairwise merge. Binary decision on pre-filtered pairs."""

    consolidation_llm_provider: str = "anthropic"
    """LLM provider for cluster consolidation (3+ item clusters)."""

    consolidation_llm_model: str = "claude-sonnet-4-6"
    """Model for consolidation. Balances reasoning with cost for N→M decisions."""

    consolidation_max_tokens: int = 4096
    """Max tokens for consolidation response."""

    review_llm_provider: str = "anthropic"
    """LLM provider for review curation. Frontier model for high-stakes decisions."""

    review_llm_model: str = "claude-opus-4-6"
    """Model for review curation (KEEP/UPDATE/RECLASSIFY/SPLIT/DELETE)."""

    llm_temperature: float = 0.3
    """Low temperature for consistent curation decisions."""

    curation_batch_size: int = 10
    """Number of knowledge items to process per LLM call in Contemplation."""

    # ─────────────────────────────────────────────────────────────
    # Per-Session Work Caps (prevents health check starvation)
    # ─────────────────────────────────────────────────────────────
    max_clusters_per_session: int = 20
    """Max similarity clusters to process per meditation session.
    Largest clusters processed first. Remainder deferred to next session."""

    max_review_candidates: int = 50
    """Max individual knowledge items to review per session.
    At batch_size=10 this means 5 LLM calls, not 100."""

    yield_interval_seconds: float = 0.2
    """Sleep between LLM calls to yield CPU to the event loop.
    Prevents health check starvation on single-core machines."""

    # ─────────────────────────────────────────────────────────────
    # Embedding Regeneration
    # ─────────────────────────────────────────────────────────────
    regenerate_embeddings: bool = True
    """Whether to regenerate embeddings after merge/split/update."""

    embedding_model: str = "text-embedding-3-small"
    """OpenAI embedding model. Matches existing Knowledge embeddings."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize config for storage in meditation_sessions.config_snapshot."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeditatorConfig":
        """Reconstruct config from stored snapshot."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
