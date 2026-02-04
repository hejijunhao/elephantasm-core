"""Embedding services for semantic vector generation."""

from functools import lru_cache

from app.core.config import settings
from .base import EmbeddingProvider
from .openai import OpenAIEmbeddingProvider


@lru_cache()
def get_embedding_provider() -> EmbeddingProvider:
    """Get configured embedding provider (singleton)."""
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for embedding generation")
    return OpenAIEmbeddingProvider(api_key=settings.OPENAI_API_KEY)


__all__ = ["EmbeddingProvider", "get_embedding_provider"]
