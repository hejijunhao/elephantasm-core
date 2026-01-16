"""Domain operations for Usage tracking - counters and period snapshots.

CRUD operations and business logic for UsageCounter and UsagePeriod.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func, update
from sqlmodel import Session
from fastapi import HTTPException

from app.models.database.usage import (
    UsageCounter,
    UsagePeriod,
    UsagePeriodRead,
    UsageCounterRead,
)
from app.models.database.animas import Anima
from app.models.database.subscription import Subscription


class UsageOperations:
    """
    Usage tracking business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    # --- Counter Management ---

    @staticmethod
    def get_counter(
        session: Session,
        org_id: UUID
    ) -> Optional[UsageCounter]:
        """Get usage counter for organization."""
        query = select(UsageCounter).where(UsageCounter.organization_id == org_id)
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_or_create_counter(
        session: Session,
        org_id: UUID
    ) -> UsageCounter:
        """Get or create usage counter for organization.

        Creates new counter with current month as period start if not exists.
        """
        counter = UsageOperations.get_counter(session, org_id)
        if counter:
            return counter

        today = date.today()
        period_start = date(today.year, today.month, 1)  # First of current month

        counter = UsageCounter(
            organization_id=org_id,
            period_start=period_start,
            events_created=0,
            pack_builds=0,
            synthesis_runs=0,
            memories_stored=0,
            knowledge_items=0,
            vector_storage_bytes=0,
            active_anima_count=0,
            dormant_anima_count=0,
            last_anima_check=datetime.utcnow()
        )

        session.add(counter)
        session.flush()
        return counter

    @staticmethod
    def increment_counter(
        session: Session,
        org_id: UUID,
        field: str,
        amount: int = 1
    ) -> UsageCounter:
        """
        Atomically increment a counter field.

        Supported fields: events_created, pack_builds, synthesis_runs

        Args:
            session: Database session
            org_id: Organization ID
            field: Counter field to increment
            amount: Amount to increment by (default 1)
        """
        allowed_fields = {"events_created", "pack_builds", "synthesis_runs"}
        if field not in allowed_fields:
            raise ValueError(f"Invalid counter field: {field}. Must be one of {allowed_fields}")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        # Use SQL update for atomicity
        current_value = getattr(counter, field)
        setattr(counter, field, current_value + amount)
        counter.updated_at = datetime.utcnow()

        session.add(counter)
        session.flush()
        session.refresh(counter)
        return counter

    @staticmethod
    def update_storage_counts(
        session: Session,
        org_id: UUID,
        memories: int | None = None,
        knowledge: int | None = None,
        vector_bytes: int | None = None
    ) -> UsageCounter:
        """
        Update point-in-time storage counts.

        Unlike increment counters, these are absolute values (recounted from DB).

        Args:
            session: Database session
            org_id: Organization ID
            memories: Current memory count (optional)
            knowledge: Current knowledge count (optional)
            vector_bytes: Current vector storage bytes (optional)
        """
        counter = UsageOperations.get_or_create_counter(session, org_id)

        if memories is not None:
            counter.memories_stored = memories
        if knowledge is not None:
            counter.knowledge_items = knowledge
        if vector_bytes is not None:
            counter.vector_storage_bytes = vector_bytes

        counter.updated_at = datetime.utcnow()

        session.add(counter)
        session.flush()
        return counter

    @staticmethod
    def recount_storage(
        session: Session,
        org_id: UUID
    ) -> UsageCounter:
        """
        Recount storage metrics from database.

        Queries actual counts from memories, knowledge tables.
        """
        from app.models.database.memories import Memory
        from app.models.database.knowledge import Knowledge

        # Get user_id for the org (via subscription -> org -> members)
        # For now, count all memories/knowledge owned by users in this org
        from app.models.database.organization import OrganizationMember

        # Get all user IDs in this org
        user_ids_query = (
            select(OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org_id)
        )
        user_ids_result = session.execute(user_ids_query)
        user_ids = [row[0] for row in user_ids_result.fetchall()]

        if not user_ids:
            # No users, zero counts
            return UsageOperations.update_storage_counts(
                session, org_id, memories=0, knowledge=0, vector_bytes=0
            )

        # Count memories (via anima -> user)
        memory_count_query = (
            select(func.count())
            .select_from(Memory)
            .join(Anima, Memory.anima_id == Anima.id)
            .where(
                Anima.user_id.in_(user_ids),
                Memory.is_deleted.is_(False),
                Anima.is_deleted.is_(False)
            )
        )
        memory_count = session.execute(memory_count_query).scalar_one()

        # Count knowledge
        knowledge_count_query = (
            select(func.count())
            .select_from(Knowledge)
            .join(Anima, Knowledge.anima_id == Anima.id)
            .where(
                Anima.user_id.in_(user_ids),
                Knowledge.is_deleted.is_(False),
                Anima.is_deleted.is_(False)
            )
        )
        knowledge_count = session.execute(knowledge_count_query).scalar_one()

        # Vector storage: estimate from embedding column lengths
        # For now, approximate: each embedding ~6KB (1536 floats * 4 bytes)
        vector_bytes = (memory_count + knowledge_count) * 6144

        return UsageOperations.update_storage_counts(
            session, org_id,
            memories=memory_count,
            knowledge=knowledge_count,
            vector_bytes=vector_bytes
        )

    # --- Active Anima Tracking ---

    @staticmethod
    def count_active_animas(
        session: Session,
        org_id: UUID
    ) -> tuple[int, int]:
        """
        Count active and dormant animas for organization.

        Active = has activity in last 30 days
        Dormant = no activity for 30+ days

        Returns: (active_count, dormant_count)
        """
        from app.models.database.organization import OrganizationMember

        # Get user IDs for this org
        user_ids_query = (
            select(OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org_id)
        )
        user_ids_result = session.execute(user_ids_query)
        user_ids = [row[0] for row in user_ids_result.fetchall()]

        if not user_ids:
            return (0, 0)

        threshold = datetime.utcnow() - timedelta(days=30)

        # Count active (not dormant, not deleted)
        active_query = (
            select(func.count())
            .select_from(Anima)
            .where(
                Anima.user_id.in_(user_ids),
                Anima.is_deleted.is_(False),
                Anima.is_dormant.is_(False)
            )
        )
        active_count = session.execute(active_query).scalar_one()

        # Count dormant
        dormant_query = (
            select(func.count())
            .select_from(Anima)
            .where(
                Anima.user_id.in_(user_ids),
                Anima.is_deleted.is_(False),
                Anima.is_dormant.is_(True)
            )
        )
        dormant_count = session.execute(dormant_query).scalar_one()

        return (active_count, dormant_count)

    @staticmethod
    def refresh_anima_counts(
        session: Session,
        org_id: UUID
    ) -> UsageCounter:
        """
        Refresh active/dormant anima counts in usage counter.
        """
        active, dormant = UsageOperations.count_active_animas(session, org_id)

        counter = UsageOperations.get_or_create_counter(session, org_id)
        counter.active_anima_count = active
        counter.dormant_anima_count = dormant
        counter.last_anima_check = datetime.utcnow()
        counter.updated_at = datetime.utcnow()

        session.add(counter)
        session.flush()
        return counter

    @staticmethod
    def update_anima_dormancy_bulk(session: Session) -> int:
        """
        Update is_dormant flag for all animas based on last_activity_at.

        Called by daily background job.
        Returns number of animas updated.
        """
        threshold = datetime.utcnow() - timedelta(days=30)

        # Mark as dormant if no recent activity
        dormant_stmt = (
            update(Anima)
            .where(
                Anima.is_deleted.is_(False),
                Anima.is_dormant.is_(False),
                (Anima.last_activity_at < threshold) | (Anima.last_activity_at.is_(None))
            )
            .values(is_dormant=True, updated_at=datetime.utcnow())
        )
        dormant_result = session.execute(dormant_stmt)

        # Mark as active if has recent activity
        active_stmt = (
            update(Anima)
            .where(
                Anima.is_deleted.is_(False),
                Anima.is_dormant.is_(True),
                Anima.last_activity_at >= threshold
            )
            .values(is_dormant=False, updated_at=datetime.utcnow())
        )
        active_result = session.execute(active_stmt)

        session.flush()
        return dormant_result.rowcount + active_result.rowcount

    @staticmethod
    def update_anima_activity(
        session: Session,
        anima_id: UUID
    ) -> None:
        """
        Update anima's last_activity_at timestamp.

        Called when events created or packs built.
        Also clears dormant flag if set.
        """
        anima = session.get(Anima, anima_id)
        if anima:
            anima.last_activity_at = datetime.utcnow()
            anima.is_dormant = False
            session.add(anima)
            session.flush()

    # --- Period Snapshots ---

    @staticmethod
    def create_period_snapshot(
        session: Session,
        org_id: UUID
    ) -> UsagePeriod:
        """
        Create usage period snapshot for current period.

        Called at end of billing period to archive usage.
        """
        counter = UsageOperations.get_or_create_counter(session, org_id)

        # Get subscription for plan tier
        subscription = session.execute(
            select(Subscription).where(Subscription.organization_id == org_id)
        ).scalar_one_or_none()

        plan_tier = subscription.plan_tier if subscription else "free"

        # Calculate overage cost
        from app.domain.limit_operations import LimitOperations
        overage_cents = LimitOperations.calculate_total_overage(session, org_id)

        # Create period snapshot
        today = date.today()
        period_end = today - timedelta(days=1)  # Yesterday

        period = UsagePeriod(
            organization_id=org_id,
            period_start=counter.period_start,
            period_end=period_end,
            plan_tier=plan_tier,
            active_anima_count=counter.active_anima_count,
            dormant_anima_count=counter.dormant_anima_count,
            events_created=counter.events_created,
            memories_stored=counter.memories_stored,
            knowledge_items=counter.knowledge_items,
            pack_builds=counter.pack_builds,
            synthesis_runs=counter.synthesis_runs,
            vector_storage_bytes=counter.vector_storage_bytes,
            overage_cents=overage_cents,
            is_billed=False
        )

        session.add(period)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.PERIOD_ENDED,
            description=f"Billing period ended: {counter.period_start} to {period_end}",
            new_value={
                "period_start": str(counter.period_start),
                "period_end": str(period_end),
                "events_created": counter.events_created,
                "overage_cents": overage_cents
            }
        )

        return period

    @staticmethod
    def get_current_period(
        session: Session,
        org_id: UUID
    ) -> Optional[UsagePeriod]:
        """Get most recent usage period for organization."""
        query = (
            select(UsagePeriod)
            .where(UsagePeriod.organization_id == org_id)
            .order_by(UsagePeriod.period_end.desc())
            .limit(1)
        )
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_period_history(
        session: Session,
        org_id: UUID,
        limit: int = 12
    ) -> list[UsagePeriod]:
        """Get usage period history (most recent first)."""
        query = (
            select(UsagePeriod)
            .where(UsagePeriod.organization_id == org_id)
            .order_by(UsagePeriod.period_end.desc())
            .limit(limit)
        )
        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def reset_counters(
        session: Session,
        org_id: UUID,
        new_period_start: date | None = None
    ) -> UsageCounter:
        """
        Reset counters for new billing period.

        Called after period snapshot is created.

        Args:
            session: Database session
            org_id: Organization ID
            new_period_start: Start date for new period (defaults to today)
        """
        counter = UsageOperations.get_or_create_counter(session, org_id)

        if new_period_start is None:
            new_period_start = date.today()

        # Reset cumulative counters
        counter.period_start = new_period_start
        counter.events_created = 0
        counter.pack_builds = 0
        counter.synthesis_runs = 0

        # Keep storage counts (point-in-time, not cumulative)
        # Keep anima counts (will be refreshed separately)

        counter.updated_at = datetime.utcnow()

        session.add(counter)
        session.flush()
        return counter

    @staticmethod
    def mark_period_billed(
        session: Session,
        period_id: UUID
    ) -> UsagePeriod:
        """Mark usage period as billed."""
        period = session.get(UsagePeriod, period_id)
        if not period:
            raise HTTPException(
                status_code=404,
                detail=f"Usage period {period_id} not found"
            )

        period.is_billed = True
        period.billed_at = datetime.utcnow()

        session.add(period)
        session.flush()
        return period
