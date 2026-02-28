"""
Memory-Event Operations - Domain Logic Layer

Business logic for Memory-Event provenance links (junction table).
Follows static method pattern: no instance state, session passed as parameter.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlmodel import Session
from app.domain.exceptions import EntityNotFoundError, DuplicateEntityError, DomainValidationError
from app.models.database.memories_events import MemoryEvent, MemoryEventCreate, MemoryEventUpdate
from app.models.database.memories import Memory
from app.models.database.events import Event


class MemoryEventOperations:
    """
    Domain operations for Memory-Event provenance links.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.

    Pattern: Static methods, sync operations, no transaction management.
    Routes handle commits/rollbacks; domain layer uses flush() only.
    """

    # ═══════════════════════════════════════════════════════════════════
    # Create Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def create_link(
        session: Session,
        link_data: MemoryEventCreate
    ) -> MemoryEvent:
        """
        Create provenance link between memory and event.

        Validates both entities exist before creating link.
        Raises DuplicateEntityError if duplicate link (unique constraint violation).

        Pattern: Validate FKs → create → add → flush.
        """
        # Validate Memory exists and is not soft-deleted
        memory = session.get(Memory, link_data.memory_id)
        if not memory or memory.is_deleted:
            raise EntityNotFoundError("Memory", link_data.memory_id)

        # Validate Event exists and is not soft-deleted
        event = session.get(Event, link_data.event_id)
        if not event or event.is_deleted:
            raise EntityNotFoundError("Event", link_data.event_id)

        # Validate both belong to same Anima
        if memory.anima_id != event.anima_id:
            raise DomainValidationError(
                f"Memory and Event must belong to same Anima (Memory: {memory.anima_id}, Event: {event.anima_id})"
            )

        # Create link (unique constraint will catch duplicates)
        link = MemoryEvent.model_validate(link_data)
        session.add(link)

        try:
            session.flush()
        except Exception as e:
            # Catch unique constraint violation
            if "unique constraint" in str(e).lower() or "duplicate" in str(e).lower():
                raise DuplicateEntityError(
                    "MemoryEvent",
                    f"Link between Memory {link_data.memory_id} and Event {link_data.event_id} already exists"
                )
            raise

        session.refresh(link)
        return link

    @staticmethod
    def create_bulk_links(
        session: Session,
        memory_id: UUID,
        event_ids: List[UUID],
        link_strength: Optional[float] = None
    ) -> List[MemoryEvent]:
        """
        Create multiple links from one memory to multiple events (batch operation).

        Useful for Cortex when synthesizing memory from 5-20 events.
        Validates Memory exists once, creates all links in one transaction.

        Pattern: Validate → bulk create → flush → refresh all.
        """
        # Validate Memory exists (only once)
        memory = session.get(Memory, memory_id)
        if not memory or memory.is_deleted:
            raise EntityNotFoundError("Memory", memory_id)

        # Validate all events belong to same Anima as Memory
        anima_id = memory.anima_id

        # Fetch all events and validate
        result = session.execute(
            select(Event).where(Event.id.in_(event_ids))
        )
        events = list(result.scalars().all())

        # Check all events found
        if len(events) != len(event_ids):
            found_ids = {e.id for e in events}
            missing_ids = set(event_ids) - found_ids
            raise EntityNotFoundError("Events", missing_ids)

        # Check all events belong to same Anima
        wrong_anima_events = [e for e in events if e.anima_id != anima_id]
        if wrong_anima_events:
            raise DomainValidationError(f"All events must belong to Anima {anima_id}")

        # Create all links
        links = []
        for event_id in event_ids:
            link_data = MemoryEventCreate(
                memory_id=memory_id,
                event_id=event_id,
                link_strength=link_strength
            )
            link = MemoryEvent.model_validate(link_data)
            session.add(link)
            links.append(link)

        session.flush()

        # Refresh all to get IDs and created_at timestamps
        for link in links:
            session.refresh(link)

        return links

    @staticmethod
    def bulk_create(
        session: Session,
        links_data: List[MemoryEventCreate]
    ) -> List[MemoryEvent]:
        """
        Create multiple memory-event links from list of MemoryEventCreate objects.

        Used by memory synthesis workflow to create all provenance links at once.
        Less validation than create_bulk_links (assumes data already validated).

        Pattern: Bulk create → flush → refresh all.
        """
        if not links_data:
            return []

        # Create all links
        links = []
        for link_data in links_data:
            link = MemoryEvent.model_validate(link_data)
            session.add(link)
            links.append(link)

        session.flush()

        # Refresh all to get IDs and created_at timestamps
        for link in links:
            session.refresh(link)

        return links

    # ═══════════════════════════════════════════════════════════════════
    # Query Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_events_for_memory(
        session: Session,
        memory_id: UUID,
        limit: int = 100
    ) -> List[Event]:
        """
        Get all events that contributed to a memory (ordered by link creation DESC).

        Returns Event objects (not links), filtering soft-deleted events.
        """
        stmt = (
            select(Event)
            .join(MemoryEvent, MemoryEvent.event_id == Event.id)
            .where(MemoryEvent.memory_id == memory_id)
            .where(Event.is_deleted.is_(False))
            .order_by(MemoryEvent.created_at.desc())
            .limit(limit)
        )
        result = session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def get_memories_for_event(
        session: Session,
        event_id: UUID,
        limit: int = 50
    ) -> List[Memory]:
        """
        Get all memories synthesized from an event (ordered by link creation DESC).

        Returns Memory objects (not links), filtering soft-deleted memories.
        """
        stmt = (
            select(Memory)
            .join(MemoryEvent, MemoryEvent.memory_id == Memory.id)
            .where(MemoryEvent.event_id == event_id)
            .where(Memory.is_deleted.is_(False))
            .order_by(MemoryEvent.created_at.desc())
            .limit(limit)
        )
        result = session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def get_links_for_memory(
        session: Session,
        memory_id: UUID,
        limit: int = 100,
        min_strength: Optional[float] = None
    ) -> List[MemoryEvent]:
        """
        Get all links for a memory (includes metadata like link_strength).

        Returns MemoryEvent objects with full link metadata.
        Optional filtering by minimum link_strength.
        """
        conditions = [MemoryEvent.memory_id == memory_id]

        # Filter by minimum strength if specified
        if min_strength is not None:
            conditions.append(MemoryEvent.link_strength >= min_strength)

        stmt = (
            select(MemoryEvent)
            .where(and_(*conditions))
            .order_by(MemoryEvent.link_strength.desc().nullslast(), MemoryEvent.created_at.desc())
            .limit(limit)
        )
        result = session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def count_events_for_memory(
        session: Session,
        memory_id: UUID
    ) -> int:
        """
        Count how many events contributed to a memory.

        Returns count of non-deleted links.
        """
        stmt = (
            select(func.count(MemoryEvent.id))
            .where(MemoryEvent.memory_id == memory_id)
        )
        result = session.execute(stmt)
        return result.scalar_one()

    # ═══════════════════════════════════════════════════════════════════
    # Delete Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def delete_link(
        session: Session,
        link_id: UUID
    ) -> None:
        """
        Delete provenance link by ID (hard delete - links are cheap to recreate).

        Raises EntityNotFoundError if link not found.

        Pattern: Fetch → delete → flush.
        """
        link = session.get(MemoryEvent, link_id)
        if not link:
            raise EntityNotFoundError("MemoryEvent", link_id)

        session.delete(link)
        session.flush()

    @staticmethod
    def delete_links_for_memory(
        session: Session,
        memory_id: UUID
    ) -> int:
        """
        Delete all links for a memory (cleanup operation).

        Returns count of deleted links.
        Useful for memory re-synthesis or cleanup.
        """
        stmt = select(MemoryEvent).where(MemoryEvent.memory_id == memory_id)
        result = session.execute(stmt)
        links = list(result.scalars().all())

        for link in links:
            session.delete(link)

        session.flush()
        return len(links)

    @staticmethod
    def delete_links_for_event(
        session: Session,
        event_id: UUID
    ) -> int:
        """
        Delete all links for an event (cleanup operation).

        Returns count of deleted links.
        Useful when event is being permanently removed.
        """
        stmt = select(MemoryEvent).where(MemoryEvent.event_id == event_id)
        result = session.execute(stmt)
        links = list(result.scalars().all())

        for link in links:
            session.delete(link)

        session.flush()
        return len(links)
