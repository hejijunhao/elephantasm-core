"""
Gather Phase - Meditation Context Collection

Collects all context needed for a meditation cycle:
- All non-deleted Knowledge for the Anima (primary target)
- Recent Knowledge (created since last meditation) for priority review
- Recent Memories (what the Anima has been learning — LLM context)
- Identity (curation lens)

Inverted from Dreamer: Knowledge is primary, Memories are context.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.domain.exceptions import EntityDeletedError, EntityNotFoundError
from app.domain.meditator_operations import MeditatorOperations
from app.models.database.animas import Anima
from app.models.database.identity import Identity
from app.models.database.knowledge import Knowledge
from app.models.database.memories import Memory


@dataclass
class MeditationContext:
    """
    All context needed for a meditation cycle.

    Gathered at the start of each meditation to provide consistent
    state throughout the curation process.
    """

    # Target Anima
    anima_id: UUID
    anima: Anima

    # Knowledge to process (primary)
    knowledge: list[Knowledge]
    """All non-deleted knowledge — the main input for curation."""

    recent_knowledge: list[Knowledge]
    """Knowledge created since last meditation — priority for Contemplation review."""

    # Context for LLM curation decisions
    memories: list[Memory]
    """Recent memories — what the Anima has been learning (LLM context)."""

    identity: Identity | None
    """Anima's identity — the lens for all curation decisions."""

    # Timing
    last_meditation_at: datetime | None
    """When last meditation completed — defines 'recent' boundary."""


def gather_meditation_context(
    session: Session,
    anima_id: UUID,
    since_last_meditation: bool = True,
) -> MeditationContext:
    """
    Gather all context needed for a meditation cycle.

    Fetches:
    - All non-deleted Knowledge for the Anima (primary)
    - Identity (curation lens)
    - Recent Memories (learning context for LLM)
    - Last meditation timestamp (for "recent" determination)

    Args:
        session: Database session
        anima_id: Target Anima ID
        since_last_meditation: If True, "recent" = since last meditation; else all

    Returns:
        MeditationContext with all data needed for meditation phases

    Raises:
        ValueError: If Anima not found
    """
    anima = session.get(Anima, anima_id)
    if not anima:
        raise EntityNotFoundError("Anima", anima_id)
    if anima.is_deleted:
        raise EntityDeletedError("Anima", anima_id)

    # Get last completed meditation for timing
    last_session = MeditatorOperations.get_last_session(
        session, anima_id, completed_only=True
    )
    last_meditation_at = last_session.completed_at if last_session else None

    # All non-deleted knowledge (primary target)
    # Capped at 1000 to prevent O(n²) self-join explosion in reflection phase
    knowledge = list(
        session.execute(
            select(Knowledge)
            .where(Knowledge.anima_id == anima_id)
            .where(Knowledge.is_deleted.is_(False))
            .order_by(Knowledge.created_at.desc())
            .limit(1000)
        ).scalars().all()
    )

    # Recent = created after last meditation (priority for Contemplation review)
    recent_knowledge: list[Knowledge] = []
    if since_last_meditation and last_meditation_at:
        recent_knowledge = [k for k in knowledge if k.created_at > last_meditation_at]
    else:
        recent_knowledge = knowledge.copy()

    # Identity (curation lens)
    identity = session.execute(
        select(Identity)
        .where(Identity.anima_id == anima_id)
        .where(Identity.is_deleted.is_(False))
    ).scalars().first()

    # Recent memories (context for LLM — what the Anima has been learning)
    memories = list(
        session.execute(
            select(Memory)
            .where(Memory.anima_id == anima_id)
            .where(Memory.is_deleted.is_(False))
            .order_by(Memory.created_at.desc())
            .limit(20)
        ).scalars().all()
    )

    return MeditationContext(
        anima_id=anima_id,
        anima=anima,
        knowledge=knowledge,
        recent_knowledge=recent_knowledge,
        memories=memories,
        identity=identity,
        last_meditation_at=last_meditation_at,
    )
