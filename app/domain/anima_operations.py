"""Domain operations for Animas - business logic layer.

CRUD operations and business logic for Animas.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlmodel import Session
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.database.animas import Anima, AnimaCreate, AnimaUpdate


class AnimaOperations:
    """
    Anima business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def create(
        session: Session,
        data: AnimaCreate,
        user_id: UUID | None = None
    ) -> Anima:
        """
        Create anima with auto-initialized synthesis config.

        Pattern: Create → add → flush → init config (no commit in domain layer).

        Args:
            session: Database session
            data: Anima creation data (name, description, meta)
            user_id: Owner user ID (typically from JWT token)
        """
        # Create anima instance
        anima = Anima(
            name=data.name,
            description=data.description,
            meta=data.meta or {},
            user_id=user_id
        )

        session.add(anima)
        session.flush()  # Get generated ID, stay in transaction

        # Auto-create synthesis config with env var defaults
        from app.domain.synthesis_config_operations import SynthesisConfigOperations
        SynthesisConfigOperations.get_or_create_default(session, anima.id)

        return anima

    @staticmethod
    def get_by_id(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Anima]:
        """Get anima by ID. Returns None if not found or soft-deleted (unless include_deleted=True)."""
        anima = session.get(Anima, anima_id)

        if anima is None:
            return None

        if not include_deleted and anima.is_deleted:
            return None

        return anima

    @staticmethod
    def get_all(
        session: Session,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[Anima]:
        """
        Get all animas (paginated). Ordered DESC (newest first).

        ⚠️ RLS Note: Results automatically filtered by user_id via RLS policies.
        No manual user_id filtering needed - database handles multi-tenant isolation.

        Args:
            session: Database session
            limit: Max results to return
            offset: Pagination offset
            include_deleted: Include soft-deleted animas
        """
        query = select(Anima)

        # Filter out soft-deleted
        if not include_deleted:
            query = query.where(Anima.is_deleted.is_(False))

        # Order by created_at (newest first)
        query = (
            query
            .order_by(Anima.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def update(
        session: Session,
        anima_id: UUID,
        data: AnimaUpdate
    ) -> Anima:
        """
        Update anima (partial). Raises HTTPException 404 (not found).

        Pattern: Fetch → modify → flush.
        """
        anima = session.get(Anima, anima_id)
        if not anima:
            raise HTTPException(
                status_code=404,
                detail=f"Anima {anima_id} not found"
            )

        # Update only provided fields
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(anima, key, value)

        session.add(anima)
        session.flush()
        return anima

    @staticmethod
    def soft_delete(
        session: Session,
        anima_id: UUID
    ) -> Anima:
        """Soft delete anima (mark as deleted, preserve for provenance)."""
        return AnimaOperations.update(
            session,
            anima_id,
            AnimaUpdate(is_deleted=True)
        )

    @staticmethod
    def restore(
        session: Session,
        anima_id: UUID
    ) -> Anima:
        """Restore soft-deleted anima."""
        return AnimaOperations.update(
            session,
            anima_id,
            AnimaUpdate(is_deleted=False)
        )

    @staticmethod
    def search_by_name(
        session: Session,
        name_query: str,
        limit: int = 50
    ) -> List[Anima]:
        """Search animas by name (partial match, case-insensitive). Excludes soft-deleted."""
        query = select(Anima).where(
            and_(
                Anima.name.ilike(f"%{name_query}%"),
                Anima.is_deleted.is_(False)
            )
        ).order_by(Anima.name.asc()).limit(limit)

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def count_all(
        session: Session,
        include_deleted: bool = False
    ) -> int:
        """Count total animas. Useful for pagination metadata."""
        query = select(func.count()).select_from(Anima)

        if not include_deleted:
            query = query.where(Anima.is_deleted.is_(False))

        result = session.execute(query)
        return result.scalar_one()

    @staticmethod
    def get_with_events(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Anima]:
        """Get anima with eager-loaded events relationship. Avoids N+1 query problem."""
        query = (
            select(Anima)
            .where(Anima.id == anima_id)
            .options(selectinload(Anima.events))
        )

        if not include_deleted:
            query = query.where(Anima.is_deleted.is_(False))

        result = session.execute(query)
        return result.scalar_one_or_none()
