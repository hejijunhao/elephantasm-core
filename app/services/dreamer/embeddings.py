"""
Dreamer Embeddings Helper

Regenerates embeddings for memories after summary changes.
Used by DreamerOperations after merge/split/update operations.
"""

import logging

from sqlmodel import Session

from app.models.database.memories import Memory
from app.services.embeddings import get_embedding_provider

logger = logging.getLogger(__name__)


def regenerate_embedding(
    session: Session,
    memory: Memory,
    model: str = "text-embedding-3-small",
) -> None:
    """
    Regenerate embedding for a memory after summary changes.

    Called by DreamerOperations after:
    - merge_memories() — new merged memory
    - split_memory() — each new split memory
    - update_memory() — if summary field changed

    Args:
        session: Database session
        memory: Memory to regenerate embedding for
        model: Embedding model name (for tracking)

    Raises:
        ValueError: If memory has no summary to embed
    """
    text = memory.summary
    if not text or not text.strip():
        logger.warning(f"Memory {memory.id} has no summary — skipping embedding")
        return

    try:
        provider = get_embedding_provider()
        memory.embedding = provider.embed_text(text)
        memory.embedding_model = model
        session.flush()
        logger.debug(f"Regenerated embedding for memory {memory.id}")
    except Exception as e:
        logger.error(f"Failed to regenerate embedding for memory {memory.id}: {e}")
        # Don't fail the dream — embedding regeneration is best-effort
        # Memory can still be searched by other means


def regenerate_embeddings_batch(
    session: Session,
    memories: list[Memory],
    model: str = "text-embedding-3-small",
) -> int:
    """
    Regenerate embeddings for multiple memories efficiently.

    Uses batch embedding API to minimize round trips.

    Args:
        session: Database session
        memories: Memories to regenerate embeddings for
        model: Embedding model name (for tracking)

    Returns:
        Number of memories successfully embedded
    """
    if not memories:
        return 0

    # Filter to memories with summaries
    valid_memories = [m for m in memories if m.summary and m.summary.strip()]
    if not valid_memories:
        return 0

    texts = [m.summary for m in valid_memories]

    try:
        provider = get_embedding_provider()
        embeddings = provider.embed_batch(texts)

        success_count = 0
        for memory, embedding in zip(valid_memories, embeddings):
            if embedding:  # Non-empty embedding
                memory.embedding = embedding
                memory.embedding_model = model
                success_count += 1

        session.flush()
        logger.info(f"Regenerated embeddings for {success_count}/{len(valid_memories)} memories")
        return success_count

    except Exception as e:
        logger.error(f"Batch embedding regeneration failed: {e}")
        return 0
