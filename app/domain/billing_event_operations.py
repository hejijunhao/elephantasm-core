"""Domain operations for Billing Events - audit logging for billing actions.

CRUD operations and business logic for BillingEvent audit log.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlmodel import Session

from app.models.database.billing import (
    BillingEvent,
    BillingEventCreate,
    BillingEventType,
)


class BillingEventOperations:
    """
    Billing event audit log business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def log_event(
        session: Session,
        org_id: UUID,
        event_type: BillingEventType | str,
        description: str,
        previous_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        stripe_event_id: str | None = None,
        actor_user_id: UUID | None = None
    ) -> BillingEvent:
        """
        Log a billing event to the audit log.

        Args:
            session: Database session
            org_id: Organization ID
            event_type: Type of billing event (enum or string)
            description: Human-readable description
            previous_value: State before change (optional)
            new_value: State after change (optional)
            stripe_event_id: Stripe event reference (optional)
            actor_user_id: User who performed action (optional, for manual actions)
        """
        # Convert enum to string if needed
        if isinstance(event_type, BillingEventType):
            event_type_str = event_type.value
        else:
            event_type_str = event_type

        event = BillingEvent(
            organization_id=org_id,
            event_type=event_type_str,
            description=description,
            previous_value=previous_value,
            new_value=new_value,
            stripe_event_id=stripe_event_id,
            actor_user_id=actor_user_id
        )

        session.add(event)
        session.flush()
        return event

    @staticmethod
    def get_by_id(
        session: Session,
        event_id: UUID
    ) -> Optional[BillingEvent]:
        """Get billing event by ID."""
        return session.get(BillingEvent, event_id)

    @staticmethod
    def get_events(
        session: Session,
        org_id: UUID,
        limit: int = 50,
        offset: int = 0,
        event_types: list[str] | None = None
    ) -> list[BillingEvent]:
        """
        Get billing events for an organization.

        Args:
            session: Database session
            org_id: Organization ID
            limit: Max results (default 50)
            offset: Pagination offset
            event_types: Filter by event types (optional)

        Returns:
            List of billing events (newest first)
        """
        query = (
            select(BillingEvent)
            .where(BillingEvent.organization_id == org_id)
        )

        if event_types:
            query = query.where(BillingEvent.event_type.in_(event_types))

        query = (
            query
            .order_by(BillingEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_by_stripe_event(
        session: Session,
        stripe_event_id: str
    ) -> Optional[BillingEvent]:
        """Get billing event by Stripe event ID (for idempotency)."""
        query = select(BillingEvent).where(
            BillingEvent.stripe_event_id == stripe_event_id
        )
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_events_by_type(
        session: Session,
        org_id: UUID,
        event_type: BillingEventType | str,
        limit: int = 10
    ) -> list[BillingEvent]:
        """Get events of a specific type for an organization."""
        event_type_str = event_type.value if isinstance(event_type, BillingEventType) else event_type

        query = (
            select(BillingEvent)
            .where(
                BillingEvent.organization_id == org_id,
                BillingEvent.event_type == event_type_str
            )
            .order_by(BillingEvent.created_at.desc())
            .limit(limit)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_recent_payment_events(
        session: Session,
        org_id: UUID,
        limit: int = 5
    ) -> list[BillingEvent]:
        """Get recent payment-related events."""
        payment_types = [
            BillingEventType.PAYMENT_SUCCEEDED.value,
            BillingEventType.PAYMENT_FAILED.value,
            BillingEventType.PAYMENT_REFUNDED.value,
        ]

        query = (
            select(BillingEvent)
            .where(
                BillingEvent.organization_id == org_id,
                BillingEvent.event_type.in_(payment_types)
            )
            .order_by(BillingEvent.created_at.desc())
            .limit(limit)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_plan_change_history(
        session: Session,
        org_id: UUID,
        limit: int = 10
    ) -> list[BillingEvent]:
        """Get plan change history."""
        plan_types = [
            BillingEventType.PLAN_CHANGED.value,
            BillingEventType.PLAN_UPGRADED.value,
            BillingEventType.PLAN_DOWNGRADED.value,
            BillingEventType.MANUAL_ASSIGNMENT.value,
        ]

        query = (
            select(BillingEvent)
            .where(
                BillingEvent.organization_id == org_id,
                BillingEvent.event_type.in_(plan_types)
            )
            .order_by(BillingEvent.created_at.desc())
            .limit(limit)
        )

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def count_events(
        session: Session,
        org_id: UUID,
        event_types: list[str] | None = None
    ) -> int:
        """Count billing events for an organization."""
        from sqlalchemy import func

        query = (
            select(func.count())
            .select_from(BillingEvent)
            .where(BillingEvent.organization_id == org_id)
        )

        if event_types:
            query = query.where(BillingEvent.event_type.in_(event_types))

        result = session.execute(query)
        return result.scalar_one()

    # --- Convenience logging methods ---

    @staticmethod
    def log_subscription_created(
        session: Session,
        org_id: UUID,
        plan_tier: str
    ) -> BillingEvent:
        """Log subscription creation."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.SUBSCRIPTION_CREATED,
            description=f"Subscription created on {plan_tier} plan",
            new_value={"plan_tier": plan_tier}
        )

    @staticmethod
    def log_payment_succeeded(
        session: Session,
        org_id: UUID,
        amount_cents: int,
        stripe_event_id: str | None = None
    ) -> BillingEvent:
        """Log successful payment."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.PAYMENT_SUCCEEDED,
            description=f"Payment of ${amount_cents / 100:.2f} succeeded",
            new_value={"amount_cents": amount_cents},
            stripe_event_id=stripe_event_id
        )

    @staticmethod
    def log_payment_failed(
        session: Session,
        org_id: UUID,
        amount_cents: int,
        reason: str | None = None,
        stripe_event_id: str | None = None
    ) -> BillingEvent:
        """Log failed payment."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.PAYMENT_FAILED,
            description=f"Payment of ${amount_cents / 100:.2f} failed" + (f": {reason}" if reason else ""),
            new_value={"amount_cents": amount_cents, "reason": reason},
            stripe_event_id=stripe_event_id
        )

    @staticmethod
    def log_overage_billed(
        session: Session,
        org_id: UUID,
        overage_cents: int,
        details: dict[str, Any] | None = None
    ) -> BillingEvent:
        """Log overage billing."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.OVERAGE_BILLED,
            description=f"Overage of ${overage_cents / 100:.2f} billed",
            new_value={"overage_cents": overage_cents, **(details or {})}
        )

    @staticmethod
    def log_overage_warning(
        session: Session,
        org_id: UUID,
        current_overage_cents: int,
        spending_cap_cents: int
    ) -> BillingEvent:
        """Log overage warning (approaching spending cap)."""
        percentage = (current_overage_cents / spending_cap_cents * 100) if spending_cap_cents > 0 else 0
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.OVERAGE_WARNING,
            description=f"Overage at {percentage:.0f}% of spending cap",
            new_value={
                "current_overage_cents": current_overage_cents,
                "spending_cap_cents": spending_cap_cents,
                "percentage": percentage
            }
        )

    @staticmethod
    def log_spending_cap_reached(
        session: Session,
        org_id: UUID,
        cap_cents: int
    ) -> BillingEvent:
        """Log spending cap reached."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.SPENDING_CAP_REACHED,
            description=f"Spending cap of ${cap_cents / 100:.2f} reached",
            new_value={"spending_cap_cents": cap_cents}
        )

    @staticmethod
    def log_referral_credit(
        session: Session,
        org_id: UUID,
        credit_cents: int,
        referral_code: str
    ) -> BillingEvent:
        """Log referral credit applied."""
        return BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.REFERRAL_CREDIT_APPLIED,
            description=f"Referral credit of ${credit_cents / 100:.2f} applied",
            new_value={"credit_cents": credit_cents, "referral_code": referral_code}
        )
