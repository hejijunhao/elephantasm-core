"""
Gather Phase - Dream Context Collection

Collects all context needed for a dream cycle:
- All ACTIVE memories for the Anima
- Recent memories (created since last dream) for priority review
- Identity (lens for LLM curation decisions)
- Knowledge (to avoid redundant memories)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.domain.dreamer_operations import DreamerOperations
from app.models.database.animas import Anima
from app.models.database.identity import Identity
from app.models.database.knowledge import Knowledge
from app.models.database.memories import Memory, MemoryState


@dataclass
class DreamContext:
    """
    All context needed for a dream cycle.

    Gathered at the start of each dream to provide consistent
    state throughout the curation process.
    """

    # Target Anima
    anima_id: UUID
    anima: Anima

    # Memories to process
    memories: list[Memory]
    """All ACTIVE memories — the main input for curation."""

    recent_memories: list[Memory]
    """Memories created since last dream — priority for Deep Sleep review."""

    # Related context for LLM curation decisions
    identity: Identity | None
    """Anima's identity — the lens for all curation decisions."""

    knowledge: list[Knowledge]
    """Existing knowledge — helps LLM avoid redundant memories."""

    # Timing
    last_dream_at: datetime | None
    """When last dream completed — defines 'recent' boundary."""


def gather_dream_context(
    session: Session,
    anima_id: UUID,
    since_last_dream: bool = True,
) -> DreamContext:
    """
    Gather all context needed for a dream cycle.

    Fetches:
    - All ACTIVE, non-deleted memories for the Anima
    - Identity (for curation lens)
    - Knowledge (to avoid redundant memories)
    - Last dream timestamp (for "recent" determination)

    Args:
        session: Database session
        anima_id: Target Anima ID
        since_last_dream: If True, "recent" = since last dream; else all

    Returns:
        DreamContext with all data needed for dream phases

    Raises:
        ValueError: If Anima not found
    """
    # Fetch Anima
    anima = session.get(Anima, anima_id)
    if not anima:
        raise ValueError(f"Anima {anima_id} not found")
    if anima.is_deleted:
        raise ValueError(f"Anima {anima_id} is deleted")

    # Get last completed dream for timing
    last_dream = DreamerOperations.get_last_session(
        session, anima_id, completed_only=True
    )
    last_dream_at = last_dream.completed_at if last_dream else None

    # All ACTIVE, non-deleted memories
    memories = list(
        session.exec(
            select(Memory)
            .where(Memory.anima_id == anima_id)
            .where(Memory.is_deleted == False)  # noqa: E712
            .where(Memory.state == MemoryState.ACTIVE)
            .order_by(Memory.created_at.desc())
        ).all()
    )

    # Recent = created after last dream (priority for Deep Sleep review)
    recent_memories: list[Memory] = []
    if since_last_dream and last_dream_at:
        recent_memories = [m for m in memories if m.created_at > last_dream_at]
    else:
        # No previous dream — all memories are "recent"
        recent_memories = memories.copy()

    # Identity (for LLM curation lens)
    identity = session.exec(
        select(Identity)
        .where(Identity.anima_id == anima_id)
        .where(Identity.is_deleted == False)  # noqa: E712
    ).first()

    # Knowledge (for redundancy check during curation)
    knowledge = list(
        session.exec(
            select(Knowledge)
            .where(Knowledge.anima_id == anima_id)
            .where(Knowledge.is_deleted == False)  # noqa: E712
        ).all()
    )

    return DreamContext(
        anima_id=anima_id,
        anima=anima,
        memories=memories,
        recent_memories=recent_memories,
        identity=identity,
        knowledge=knowledge,
        last_dream_at=last_dream_at,
    )
