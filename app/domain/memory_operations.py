"""
Memory Operations - Domain Logic Layer

Business logic for Memory entity CRUD and queries.
Follows static method pattern: no instance state, session passed as parameter.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlmodel import Session
from fastapi import HTTPException

from app.models.database.memories import Memory, MemoryCreate, MemoryUpdate, MemoryState
from app.models.database.animas import Anima


class MemoryOperations:
    """
    Domain operations for Memory entity.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.

    Pattern: Static methods, sync operations, no transaction management.
    Routes handle commits/rollbacks; domain layer uses flush() only.
    """

    # ═══════════════════════════════════════════════════════════════════
    # Core CRUD Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def create(session: Session, data: MemoryCreate) -> Memory:
        """
        Create new memory with Anima FK validation. Raises 404 if Anima not found.

        Note: All fields except anima_id are now optional (nullable).

        Pattern: Validate FK → create → add → flush.
        """
        # Validate Anima exists and is not soft-deleted
        anima_result = session.execute(
            select(Anima).where(
                and_(
                    Anima.id == data.anima_id,
                    Anima.is_deleted.is_(False)
                )
            )
        )
        anima = anima_result.scalar_one_or_none()
        if not anima:
            raise HTTPException(
                status_code=404,
                detail=f"Anima {data.anima_id} not found"
            )

        # Create memory (all fields nullable - no defaults needed)
        memory = Memory(**data.model_dump())
        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def get_by_id(
        session: Session,
        memory_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Memory]:
        """Get memory by ID. Returns None if not found or soft-deleted (unless include_deleted=True)."""
        result = session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            return None

        # Filter soft-deleted unless explicitly requested
        if memory.is_deleted and not include_deleted:
            return None

        return memory

    @staticmethod
    def get_by_anima(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0,
        state: Optional[MemoryState] = None,
        include_deleted: bool = False
    ) -> List[Memory]:
        """Get memories for anima (paginated, filterable by state). Ordered by time_end DESC."""
        # Build query with filters
        conditions = [Memory.anima_id == anima_id]

        if state is not None:
            conditions.append(Memory.state == state)

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        # Execute query with ordering and pagination
        result = session.execute(
            select(Memory)
            .where(and_(*conditions))
            .order_by(Memory.time_end.desc(), Memory.created_at.desc())
            .limit(min(limit, 200))  # Cap at 200
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    def update(
        session: Session,
        memory_id: UUID,
        data: MemoryUpdate
    ) -> Memory:
        """
        Partial update of memory. Raises 404 if not found.

        Pattern: Fetch → modify → flush.
        """
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise HTTPException(
                status_code=404,
                detail=f"Memory {memory_id} not found"
            )

        # Update only provided fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(memory, field, value)

        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def soft_delete(session: Session, memory_id: UUID) -> Memory:
        """Mark memory as deleted (provenance preservation). Raises 404 if not found."""
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise HTTPException(
                status_code=404,
                detail=f"Memory {memory_id} not found"
            )

        memory.is_deleted = True
        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def restore(session: Session, memory_id: UUID) -> Memory:
        """Restore soft-deleted memory. Raises 404 if not found."""
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise HTTPException(
                status_code=404,
                detail=f"Memory {memory_id} not found"
            )

        memory.is_deleted = False
        session.add(memory)
        session.flush()
        return memory

    # ═══════════════════════════════════════════════════════════════════
    # Query Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_active(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[Memory]:
        """Get only active memories for anima. Convenience wrapper for get_by_anima()."""
        return MemoryOperations.get_by_anima(
            session=session,
            anima_id=anima_id,
            limit=limit,
            offset=offset,
            state=MemoryState.ACTIVE,
            include_deleted=False
        )

    @staticmethod
    def get_by_state(
        session: Session,
        anima_id: UUID,
        state: MemoryState,
        limit: int = 50,
        offset: int = 0
    ) -> List[Memory]:
        """Get memories by lifecycle state. Convenience wrapper for get_by_anima()."""
        return MemoryOperations.get_by_anima(
            session=session,
            anima_id=anima_id,
            limit=limit,
            offset=offset,
            state=state,
            include_deleted=False
        )

    @staticmethod
    def search_by_summary(
        session: Session,
        anima_id: UUID,
        summary_query: str,
        limit: int = 50
    ) -> List[Memory]:
        """Search memories by summary text (case-insensitive partial match). Ordered by importance DESC."""
        result = session.execute(
            select(Memory)
            .where(
                and_(
                    Memory.anima_id == anima_id,
                    Memory.summary.ilike(f"%{summary_query}%"),
                    Memory.is_deleted.is_(False)
                )
            )
            .order_by(Memory.importance.desc())
            .limit(min(limit, 200))
        )
        return list(result.scalars().all())

    @staticmethod
    def count_by_anima(
        session: Session,
        anima_id: UUID,
        state: Optional[MemoryState] = None,
        include_deleted: bool = False
    ) -> int:
        """Count memories for anima with optional filters."""
        conditions = [Memory.anima_id == anima_id]

        if state is not None:
            conditions.append(Memory.state == state)

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        result = session.execute(
            select(func.count()).select_from(Memory).where(and_(*conditions))
        )
        return result.scalar_one()

    @staticmethod
    def get_last_memory_time(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> Optional[datetime]:
        """
        Get timestamp of most recent memory for anima.

        Returns None if anima has no memories (caller should fall back to anima.created_at).
        """
        conditions = [Memory.anima_id == anima_id]

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        result = session.execute(
            select(Memory.created_at)
            .where(and_(*conditions))
            .order_by(Memory.created_at.desc())
            .limit(1)
        )

        row = result.first()
        return row[0] if row else None

    # ═══════════════════════════════════════════════════════════════════
    # Convenience Helpers (for Dreamer and curation)
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def update_importance(
        session: Session,
        memory_id: UUID,
        importance: float
    ) -> Memory:
        """Update importance score only. Convenience wrapper for Dreamer curation."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(importance=importance)
        )

    @staticmethod
    def update_confidence(
        session: Session,
        memory_id: UUID,
        confidence: float
    ) -> Memory:
        """Update confidence score only. Convenience wrapper for Dreamer curation."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(confidence=confidence)
        )

    @staticmethod
    def transition_state(
        session: Session,
        memory_id: UUID,
        new_state: MemoryState
    ) -> Memory:
        """Update memory lifecycle state. Convenience wrapper for Dreamer state transitions."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(state=new_state)
        )

    # ═══════════════════════════════════════════════════════════════════
    # Score Computation Helpers (TODO: Implement in future iteration)
    # ═══════════════════════════════════════════════════════════════════

    # @staticmethod
    # def compute_recency_score(
    #     time_end: datetime,
    #     now: Optional[datetime] = None
    # ) -> float:
    #     """
    #     Calculate recency score using exponential decay (30-day half-life).
    #     TODO: Implement in separate iteration.
    #     """
    #     pass

    # @staticmethod
    # def compute_decay_score(
    #     importance: float,
    #     confidence: float,
    #     recency_score: float
    # ) -> float:
    #     """
    #     Calculate composite decay score (weighted: 40% importance, 30% confidence, 30% recency).
    #     TODO: Implement in separate iteration.
    #     """
    #     pass
