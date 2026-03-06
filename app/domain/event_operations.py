"""Domain operations for Events - business logic layer.

CRUD operations and business logic for Events.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
import hashlib

from sqlalchemy import select, and_, func
from sqlmodel import Session
from app.domain.exceptions import EntityNotFoundError, DomainValidationError
from app.models.database.events import Event, EventCreate, EventUpdate
from app.models.database.animas import Anima


class EventOperations:
    """
    Event business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def create(
        session: Session,
        data: EventCreate,
        skip_usage_tracking: bool = False
    ) -> Event:
        # Create event. Validates Anima FK, auto-defaults occurred_at, generates dedupe_key if needed.
        # Validate anima exists
        anima = session.get(Anima, data.anima_id)
        if not anima or anima.is_deleted:
            raise EntityNotFoundError("Anima", data.anima_id)

        # Default occurred_at to current time if not provided
        occurred_at = data.occurred_at if data.occurred_at else datetime.now(timezone.utc)

        # Auto-generate dedupe_key if source_uri provided but no dedupe_key
        dedupe_key = data.dedupe_key
        if data.source_uri and not dedupe_key:
            dedupe_key = EventOperations._generate_dedupe_key(
                anima_id=data.anima_id,
                event_type=data.event_type,
                content=data.content,
                occurred_at=occurred_at,
                source_uri=data.source_uri
            )

        # Validate importance_score if provided
        if data.importance_score is not None:
            if not (0.0 <= data.importance_score <= 1.0):
                raise DomainValidationError("importance_score must be between 0.0 and 1.0")

        # Create event instance
        event = Event(
            anima_id=data.anima_id,
            event_type=data.event_type,
            role=data.role,
            author=data.author,
            content=data.content,
            summary=data.summary,
            occurred_at=occurred_at,
            session_id=data.session_id,
            meta=data.meta or {},
            source_uri=data.source_uri,
            dedupe_key=dedupe_key,
            importance_score=data.importance_score
        )

        session.add(event)
        session.flush()  # Get generated ID, stay in transaction

        # Track usage (update anima activity + increment counter)
        if not skip_usage_tracking:
            EventOperations._track_event_usage(session, anima)

        return event

    @staticmethod
    def _track_event_usage(session: Session, anima: Anima) -> None:
        """Track event creation usage. Updates anima activity and increments org counter."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.organization_operations import OrganizationOperations

        # Update anima activity
        UsageOperations.update_anima_activity(session, anima.id)

        # Increment org usage counter if user is linked to org
        if anima.user_id:
            org = OrganizationOperations.get_primary_org_for_user(session, anima.user_id)
            if org:
                UsageOperations.increment_counter(session, org.id, "events_created")

    @staticmethod
    def get_by_id(
        session: Session,
        event_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Event]:
        """Get event by ID. Returns None if not found or soft-deleted (unless include_deleted=True)."""
        event = session.get(Event, event_id)

        if event is None:
            return None

        if not include_deleted and event.is_deleted:
            return None

        return event

    @staticmethod
    def get_recent(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        min_importance: Optional[float] = None,
        include_deleted: bool = False
    ) -> List[Event]:
        """Get recent events for anima with filters. Ordered DESC (newest first), paginated."""
        query = select(Event).where(Event.anima_id == anima_id)

        # Apply filters
        if not include_deleted:
            query = query.where(Event.is_deleted.is_(False))

        if event_type:
            query = query.where(Event.event_type == event_type)

        if session_id:
            query = query.where(Event.session_id == session_id)

        if min_importance is not None:
            query = query.where(Event.importance_score >= min_importance)

        # Order by occurred_at (most recent first), with created_at as tiebreaker
        query = (
            query
            .order_by(Event.occurred_at.desc(), Event.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_by_session(
        session: Session,
        anima_id: UUID,
        session_id: str,
        include_deleted: bool = False,
        limit: int = 200,
        offset: int = 0,
        event_type: Optional[str] = None,
        min_importance: Optional[float] = None,
    ) -> List[Event]:
        """Get events in session. Ordered ASC (chronological), with filters and pagination."""
        conditions = [
            Event.anima_id == anima_id,
            Event.session_id == session_id
        ]

        if not include_deleted:
            conditions.append(Event.is_deleted.is_(False))

        if event_type:
            conditions.append(Event.event_type == event_type)

        if min_importance is not None:
            conditions.append(Event.importance_score >= min_importance)

        result = session.execute(
            select(Event)
            .where(and_(*conditions))
            .order_by(Event.occurred_at.asc(), Event.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    def count_by_anima(
        session: Session,
        anima_id: UUID,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        include_deleted: bool = False
    ) -> int:
        """Count events for anima with optional filters."""
        query = select(func.count()).select_from(Event).where(Event.anima_id == anima_id)

        if not include_deleted:
            query = query.where(Event.is_deleted.is_(False))

        if event_type:
            query = query.where(Event.event_type == event_type)

        if session_id:
            query = query.where(Event.session_id == session_id)

        result = session.execute(query)
        return result.scalar_one()

    @staticmethod
    def count_since(
        session: Session,
        anima_id: UUID,
        since: datetime,
        include_deleted: bool = False
    ) -> int:
        """
        Count events for anima since timestamp.

        Args:
            session: Database session
            anima_id: Anima UUID
            since: Cutoff timestamp (events after this)
            include_deleted: Whether to include soft-deleted events

        Returns:
            Count of events since timestamp
        """
        conditions = [
            Event.anima_id == anima_id,
            Event.occurred_at > since
        ]

        if not include_deleted:
            conditions.append(Event.is_deleted.is_(False))

        result = session.execute(
            select(func.count())
            .select_from(Event)
            .where(and_(*conditions))
        )
        return result.scalar_one()

    @staticmethod
    def get_since(
        session: Session,
        anima_id: UUID,
        since: datetime,
        include_deleted: bool = False,
        limit: Optional[int] = None
    ) -> List[Event]:
        """
        Fetch events for anima since timestamp (chronological order).

        Args:
            session: Database session
            anima_id: Anima UUID
            since: Cutoff timestamp (events after this)
            include_deleted: Whether to include soft-deleted events
            limit: Max events to return (None = unlimited)

        Returns:
            List of events ordered by occurred_at ascending
        """
        conditions = [
            Event.anima_id == anima_id,
            Event.occurred_at > since
        ]

        if not include_deleted:
            conditions.append(Event.is_deleted.is_(False))

        query = (
            select(Event)
            .where(and_(*conditions))
            .order_by(Event.occurred_at.asc())
        )

        if limit:
            query = query.limit(limit)

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def update(
        session: Session,
        event_id: UUID,
        data: EventUpdate
    ) -> Event:
        """
        Update event (partial). Validates importance_score range.

        Raises EntityNotFoundError or DomainValidationError.

        Pattern: Fetch → validate → modify → flush.
        """
        event = session.get(Event, event_id)
        if not event:
            raise EntityNotFoundError("Event", event_id)

        # Validate importance_score if being updated
        if data.importance_score is not None:
            if not (0.0 <= data.importance_score <= 1.0):
                raise DomainValidationError("importance_score must be between 0.0 and 1.0")

        # Update only provided fields
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(event, key, value)

        session.add(event)
        session.flush()
        return event

    @staticmethod
    def update_summary(
        session: Session,
        event_id: UUID,
        summary: str
    ) -> Event:
        """Update summary (typically populated by Cortex)."""
        return EventOperations.update(
            session,
            event_id,
            EventUpdate(summary=summary)
        )

    @staticmethod
    def update_importance(
        session: Session,
        event_id: UUID,
        importance_score: float
    ) -> Event:
        """Update importance_score (0.0-1.0 range validated)."""
        return EventOperations.update(
            session,
            event_id,
            EventUpdate(importance_score=importance_score)
        )

    @staticmethod
    def soft_delete(
        session: Session,
        event_id: UUID
    ) -> Event:
        """Soft delete event (mark as deleted, preserve for provenance)."""
        return EventOperations.update(
            session,
            event_id,
            EventUpdate(is_deleted=True)
        )

    @staticmethod
    def restore(
        session: Session,
        event_id: UUID
    ) -> Event:
        """Restore soft-deleted event."""
        return EventOperations.update(
            session,
            event_id,
            EventUpdate(is_deleted=False)
        )

    @staticmethod
    def _generate_dedupe_key(
        anima_id: UUID,
        event_type: str,
        content: str,
        occurred_at: datetime,
        source_uri: str
    ) -> str:
        """Generate dedupe key: SHA256 hash (first 100 chars of content) truncated to 32 chars."""
        parts = [
            str(anima_id),
            event_type,
            (content or "")[:100],  # First 100 chars only
            occurred_at.isoformat(),
            source_uri
        ]
        hash_input = "|".join(parts).encode()
        return hashlib.sha256(hash_input).hexdigest()[:32]
