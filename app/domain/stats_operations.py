"""Domain operations for Stats - aggregated counts for settings/usage page.

RLS-aware: All counts automatically filtered by authenticated user.
"""

from sqlalchemy import select, func
from sqlmodel import Session

from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.knowledge import Knowledge


class StatsOperations:
    """
    Stats aggregation operations. Static methods, sync session-based.

    All queries are RLS-aware - database policies filter by user_id automatically.
    """

    @staticmethod
    def get_overview(session: Session) -> dict:
        """
        Get aggregated counts for user's data.

        Returns:
            dict with keys: animas, events, memories, knowledge

        Note: RLS policies automatically filter by authenticated user.
        Soft-deleted items are excluded from counts.
        """
        # Count animas (excluding soft-deleted)
        animas_count = session.execute(
            select(func.count()).select_from(Anima).where(Anima.is_deleted.is_(False))
        ).scalar_one()

        # Count events (excluding soft-deleted)
        events_count = session.execute(
            select(func.count()).select_from(Event).where(Event.is_deleted.is_(False))
        ).scalar_one()

        # Count memories (excluding soft-deleted)
        memories_count = session.execute(
            select(func.count()).select_from(Memory).where(Memory.is_deleted.is_(False))
        ).scalar_one()

        # Count knowledge (excluding soft-deleted)
        knowledge_count = session.execute(
            select(func.count()).select_from(Knowledge).where(Knowledge.is_deleted.is_(False))
        ).scalar_one()

        return {
            "animas": animas_count,
            "events": events_count,
            "memories": memories_count,
            "knowledge": knowledge_count
        }
