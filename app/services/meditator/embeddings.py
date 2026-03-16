"""
Meditator Embeddings Helper

Regenerates embeddings for knowledge items after content changes.
Used by MeditatorOperations after merge/split/update operations.
"""

import logging

from sqlmodel import Session

from app.models.database.knowledge import Knowledge
from app.services.embeddings import get_embedding_provider

logger = logging.getLogger(__name__)


def regenerate_knowledge_embedding(
    session: Session,
    knowledge: Knowledge,
    model: str = "text-embedding-3-small",
) -> None:
    """
    Regenerate embedding for a knowledge item after content changes.

    Args:
        session: Database session
        knowledge: Knowledge item to regenerate embedding for
        model: Embedding model name (for tracking)
    """
    text = knowledge.content
    if not text or not text.strip():
        logger.warning(f"Knowledge {knowledge.id} has no content — skipping embedding")
        return

    try:
        provider = get_embedding_provider()
        knowledge.embedding = provider.embed_text(text)
        knowledge.embedding_model = model
        session.flush()
        logger.debug(f"Regenerated embedding for knowledge {knowledge.id}")
    except Exception as e:
        logger.warning(
            f"Failed to regenerate embedding for knowledge {knowledge.id}: "
            f"{type(e).__name__}: {e}"
        )
        # Don't fail the meditation — embedding regeneration is best-effort
