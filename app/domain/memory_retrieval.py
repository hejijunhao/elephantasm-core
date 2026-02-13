"""
Memory Retrieval - Domain Logic for Pack Compiler

Specialized retrieval operations for memory pack compilation.
Provides time-windowed queries that complement MemoryOperations.

Pattern: Sync static methods, session passed explicitly.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, or_
from sqlmodel import Session

from app.models.database.memories import Memory, MemoryState
from app.models.database.events import Event, EventType
from app.models.database.memories_events import MemoryEvent
from app.models.dto.retrieval import TemporalContext


class MemoryRetrieval:
    """
    Retrieval operations for Pack Compiler.

    Focuses on time-windowed queries for session vs long-term memory separation.
    """

    @staticmethod
    def get_by_time_window(
        session: Session,
        anima_id: UUID,
        states: Optional[List[MemoryState]] = None,
        min_time: Optional[datetime] = None,
        max_time: Optional[datetime] = None,
        min_importance: Optional[float] = None,
        min_confidence: Optional[float] = None,
        limit: int = 50,
    ) -> List[Memory]:
        """
        Get memories within a time window.

        Used by Pack Compiler to separate session memories (recent) from
        long-term memories (older than session window).

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            states: Memory states to include (default: [ACTIVE])
            min_time: Minimum created_at (inclusive)
            max_time: Maximum created_at (exclusive)
            min_importance: Minimum importance threshold
            min_confidence: Minimum confidence threshold
            limit: Max results

        Returns:
            List of memories ordered by created_at DESC
        """
        # Default to ACTIVE state
        if states is None:
            states = [MemoryState.ACTIVE]

        # Build conditions
        conditions = [
            Memory.anima_id == anima_id,
            Memory.is_deleted.is_(False),
        ]

        # State filter (OR across states)
        if states:
            conditions.append(Memory.state.in_(states))

        # Time window
        if min_time is not None:
            conditions.append(Memory.created_at >= min_time)
        if max_time is not None:
            conditions.append(Memory.created_at < max_time)

        # Score thresholds
        if min_importance is not None:
            conditions.append(Memory.importance >= min_importance)
        if min_confidence is not None:
            conditions.append(Memory.confidence >= min_confidence)

        # Execute query
        result = session.execute(
            select(Memory)
            .where(and_(*conditions))
            .order_by(Memory.created_at.desc())
            .limit(min(limit, 200))
        )

        return list(result.scalars().all())

    @staticmethod
    def get_session_memories(
        session: Session,
        anima_id: UUID,
        session_cutoff: datetime,
        limit: int = 10,
    ) -> List[Memory]:
        """
        Get recent memories within session window.

        Convenience wrapper for session memory retrieval (Layer 2).
        Returns memories newer than session_cutoff, ordered by recency.

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            session_cutoff: Earliest time to include
            limit: Max results

        Returns:
            List of memories ordered by created_at DESC (most recent first)
        """
        return MemoryRetrieval.get_by_time_window(
            session=session,
            anima_id=anima_id,
            states=[MemoryState.ACTIVE],
            min_time=session_cutoff,
            limit=limit,
        )

    @staticmethod
    def get_long_term_memories(
        session: Session,
        anima_id: UUID,
        session_cutoff: datetime,
        states: Optional[List[MemoryState]] = None,
        min_importance: Optional[float] = None,
        limit: int = 50,
    ) -> List[Memory]:
        """
        Get memories older than session window.

        Convenience wrapper for long-term memory retrieval (Layer 4).
        Returns memories older than session_cutoff for semantic scoring.

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            session_cutoff: Latest time to include (exclusive)
            states: Memory states to include
            min_importance: Minimum importance threshold
            limit: Max results

        Returns:
            List of memories ordered by created_at DESC
        """
        if states is None:
            states = [MemoryState.ACTIVE]

        return MemoryRetrieval.get_by_time_window(
            session=session,
            anima_id=anima_id,
            states=states,
            max_time=session_cutoff,
            min_importance=min_importance,
            limit=limit,
        )

    @staticmethod
    def get_with_embeddings(
        session: Session,
        anima_id: UUID,
        states: Optional[List[MemoryState]] = None,
        max_time: Optional[datetime] = None,
        min_importance: Optional[float] = None,
        limit: int = 100,
    ) -> List[Memory]:
        """
        Get memories that have embeddings (for semantic search).

        Used when we need to compute similarity scores manually.

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            states: Memory states to include
            max_time: Maximum created_at (for excluding session memories)
            min_importance: Minimum importance threshold
            limit: Max results

        Returns:
            List of memories with embeddings
        """
        if states is None:
            states = [MemoryState.ACTIVE]

        conditions = [
            Memory.anima_id == anima_id,
            Memory.is_deleted.is_(False),
            Memory.embedding.isnot(None),
        ]

        if states:
            conditions.append(Memory.state.in_(states))

        if max_time is not None:
            conditions.append(Memory.created_at < max_time)

        if min_importance is not None:
            conditions.append(Memory.importance >= min_importance)

        result = session.execute(
            select(Memory)
            .where(and_(*conditions))
            .order_by(Memory.created_at.desc())
            .limit(min(limit, 200))
        )

        return list(result.scalars().all())

    @staticmethod
    def get_temporal_context(
        session: Session,
        anima_id: UUID,
    ) -> Optional[TemporalContext]:
        """
        Find most recent message event and its linked memory.

        Used for temporal awareness when session_memories is empty.
        Bridges gaps by providing context about when the last interaction occurred.

        Args:
            session: Database session
            anima_id: Anima to retrieve for

        Returns:
            TemporalContext if recent events exist, None otherwise
        """
        now = datetime.now(timezone.utc)

        # Query most recent MESSAGE_IN or MESSAGE_OUT event with optional linked memory
        result = session.execute(
            select(Event, Memory.summary)
            .outerjoin(MemoryEvent, MemoryEvent.event_id == Event.id)
            .outerjoin(
                Memory,
                and_(
                    Memory.id == MemoryEvent.memory_id,
                    Memory.is_deleted.is_(False),
                ),
            )
            .where(
                and_(
                    Event.anima_id == anima_id,
                    or_(
                        Event.event_type == EventType.MESSAGE_IN.value,
                        Event.event_type == EventType.MESSAGE_OUT.value,
                    ),
                    Event.is_deleted.is_(False),
                )
            )
            .order_by(Event.occurred_at.desc().nulls_last(), Event.created_at.desc())
            .limit(1)
        )

        row = result.first()
        if not row:
            return None

        event, memory_summary = row

        # Calculate time delta
        event_time = event.occurred_at or event.created_at
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        delta = now - event_time
        hours_ago = delta.total_seconds() / 3600

        # Format the temporal context string
        formatted = _format_temporal_context(hours_ago, memory_summary)

        return TemporalContext(
            last_event_at=event_time,
            hours_ago=round(hours_ago, 1),
            memory_summary=memory_summary,
            formatted=formatted,
        )


def _format_temporal_context(hours_ago: float, memory_summary: Optional[str]) -> str:
    """
    Format temporal context into a human-readable string.

    Examples:
    - "Your last communication with the user was less than an hour ago."
    - "Your last communication with the user was 3 hours ago."
    - "Your last communication with the user was yesterday about project deadlines."
    - "Your last communication with the user was 5 days ago about their vacation plans."
    """
    # Human-readable time delta
    if hours_ago < 1:
        time_str = "less than an hour ago"
    elif hours_ago < 24:
        hours = int(hours_ago)
        time_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif hours_ago < 48:
        time_str = "yesterday"
    else:
        days = int(hours_ago / 24)
        time_str = f"{days} day{'s' if days != 1 else ''} ago"

    if memory_summary:
        # Clean up summary: lowercase first letter if not acronym, strip trailing period
        summary_clean = memory_summary.rstrip(".")
        if summary_clean and summary_clean[0].isupper() and not summary_clean[:2].isupper():
            summary_clean = summary_clean[0].lower() + summary_clean[1:]
        return f"Your last communication with the user was {time_str} about {summary_clean}."
    else:
        return f"Your last communication with the user was {time_str}."
