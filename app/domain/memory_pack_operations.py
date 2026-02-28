"""Domain operations for MemoryPack - business logic layer.

CRUD operations for persisted memory packs.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import Integer
from sqlmodel import Session, select, func, desc, delete

from app.models.database.memory_pack import MemoryPack, MemoryPackStats


class MemoryPackOperations:
    """
    MemoryPack business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def create(
        session: Session,
        pack: MemoryPack,
        skip_usage_tracking: bool = False
    ) -> MemoryPack:
        """
        Persist a compiled memory pack.

        Args:
            session: Database session
            pack: MemoryPack to persist
            skip_usage_tracking: Skip incrementing usage counter

        Returns:
            Persisted MemoryPack
        """
        session.add(pack)
        session.flush()
        session.refresh(pack)

        # Track usage (increment pack_builds counter)
        if not skip_usage_tracking:
            MemoryPackOperations._track_pack_usage(session, pack.anima_id)

        return pack

    @staticmethod
    def _track_pack_usage(session: Session, anima_id: UUID) -> None:
        """Track pack build usage. Updates anima activity and increments org counter."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.organization_operations import OrganizationOperations
        from app.models.database.animas import Anima

        # Update anima activity
        UsageOperations.update_anima_activity(session, anima_id)

        # Increment org usage counter if user is linked to org
        anima = session.get(Anima, anima_id)
        if anima and anima.user_id:
            org = OrganizationOperations.get_primary_org_for_user(session, anima.user_id)
            if org:
                UsageOperations.increment_counter(session, org.id, "pack_builds")

    @staticmethod
    def get_by_id(
        session: Session,
        pack_id: UUID
    ) -> Optional[MemoryPack]:
        """
        Get pack by ID.

        Returns:
            MemoryPack if found, None otherwise
        """
        statement = select(MemoryPack).where(MemoryPack.id == pack_id)
        return session.exec(statement).first()

    @staticmethod
    def get_by_anima(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> list[MemoryPack]:
        """
        Get packs for anima, newest first.

        Args:
            session: Database session
            anima_id: Anima UUID
            limit: Max results (default 50)
            offset: Pagination offset

        Returns:
            List of MemoryPacks ordered by compiled_at desc
        """
        statement = (
            select(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
            .order_by(desc(MemoryPack.compiled_at))
            .offset(offset)
            .limit(limit)
        )
        return list(session.exec(statement).all())

    @staticmethod
    def get_latest(
        session: Session,
        anima_id: UUID
    ) -> Optional[MemoryPack]:
        """
        Get most recent pack for anima.

        Returns:
            Latest MemoryPack if exists, None otherwise
        """
        statement = (
            select(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
            .order_by(desc(MemoryPack.compiled_at))
            .limit(1)
        )
        return session.exec(statement).first()

    @staticmethod
    def count_by_anima(
        session: Session,
        anima_id: UUID
    ) -> int:
        """
        Count packs for anima.

        Returns:
            Total pack count
        """
        statement = (
            select(func.count())
            .select_from(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
        )
        return session.exec(statement).one()

    @staticmethod
    def get_stats(
        session: Session,
        anima_id: UUID
    ) -> MemoryPackStats:
        """
        Get statistics for memory packs.

        Returns:
            MemoryPackStats with aggregated metrics
        """
        # Count total packs
        count_stmt = (
            select(func.count())
            .select_from(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
        )
        total_packs = session.exec(count_stmt).one()

        if total_packs == 0:
            return MemoryPackStats(
                total_packs=0,
                avg_token_count=0.0,
                avg_session_memories=0.0,
                avg_knowledge=0.0,
                avg_long_term_memories=0.0,
                identity_usage_rate=0.0,
            )

        # Aggregate averages
        avg_stmt = select(
            func.avg(MemoryPack.token_count).label("avg_tokens"),
            func.avg(MemoryPack.session_memory_count).label("avg_session"),
            func.avg(MemoryPack.knowledge_count).label("avg_knowledge"),
            func.avg(MemoryPack.long_term_memory_count).label("avg_longterm"),
            func.sum(func.cast(MemoryPack.has_identity, Integer)).label("identity_count"),
        ).where(MemoryPack.anima_id == anima_id)

        result = session.exec(avg_stmt).one()

        return MemoryPackStats(
            total_packs=total_packs,
            avg_token_count=float(result.avg_tokens or 0),
            avg_session_memories=float(result.avg_session or 0),
            avg_knowledge=float(result.avg_knowledge or 0),
            avg_long_term_memories=float(result.avg_longterm or 0),
            identity_usage_rate=(float(result.identity_count or 0) / total_packs) * 100,
        )

    @staticmethod
    def delete_old_packs(
        session: Session,
        anima_id: UUID,
        keep_count: int = 100
    ) -> int:
        """
        Delete oldest packs beyond retention limit.

        Keeps the most recent `keep_count` packs.

        Args:
            session: Database session
            anima_id: Anima UUID
            keep_count: Number of recent packs to keep

        Returns:
            Number of packs deleted
        """
        # Get IDs of packs to keep (most recent)
        keep_stmt = (
            select(MemoryPack.id)
            .where(MemoryPack.anima_id == anima_id)
            .order_by(desc(MemoryPack.compiled_at))
            .limit(keep_count)
        )
        keep_ids = set(session.exec(keep_stmt).all())

        # Get all pack IDs for this anima
        all_stmt = (
            select(MemoryPack.id)
            .where(MemoryPack.anima_id == anima_id)
        )
        all_ids = set(session.exec(all_stmt).all())

        # IDs to delete
        delete_ids = all_ids - keep_ids

        if not delete_ids:
            return 0

        # Delete old packs
        for pack_id in delete_ids:
            pack = session.get(MemoryPack, pack_id)
            if pack:
                session.delete(pack)

        session.flush()
        return len(delete_ids)

    @staticmethod
    def enforce_retention(
        session: Session,
        anima_id: UUID,
        max_packs: int = 100
    ) -> int:
        """
        Enforce retention policy by deleting oldest packs beyond limit.

        More efficient than delete_old_packs - uses single SQL DELETE.
        Designed for fire-and-forget background tasks.

        Args:
            session: Database session
            anima_id: Anima UUID
            max_packs: Maximum packs to retain (default 100)

        Returns:
            Number of packs deleted
        """
        # Subquery: IDs of packs to keep (newest N)
        keep_subquery = (
            select(MemoryPack.id)
            .where(MemoryPack.anima_id == anima_id)
            .order_by(desc(MemoryPack.compiled_at))
            .limit(max_packs)
        )
        keep_ids = list(session.exec(keep_subquery).all())

        if not keep_ids:
            return 0

        # Delete all packs NOT in the keep list
        delete_stmt = (
            delete(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
            .where(MemoryPack.id.not_in(keep_ids))
        )
        result = session.execute(delete_stmt)
        session.flush()
        return result.rowcount

    @staticmethod
    def delete_by_id(
        session: Session,
        pack_id: UUID
    ) -> bool:
        """
        Delete a specific pack by ID.

        Returns:
            True if deleted, False if not found
        """
        pack = MemoryPackOperations.get_by_id(session, pack_id)
        if not pack:
            return False

        session.delete(pack)
        session.flush()
        return True
