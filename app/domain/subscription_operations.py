"""Domain operations for Subscriptions - billing subscription management.

CRUD operations and business logic for Subscriptions.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlmodel import Session
from fastapi import HTTPException

from app.models.database.subscription import (
    Subscription,
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionStatus,
    SpendingCapUpdate,
    AdminPlanAssignment,
)
from app.models.database.organization import Organization, OrganizationMember
from app.config.plans import get_plan, PLANS


class SubscriptionOperations:
    """
    Subscription business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def create(
        session: Session,
        data: SubscriptionCreate
    ) -> Subscription:
        """
        Create subscription for an organization.

        Sets initial billing period (1 month from now).

        Args:
            session: Database session
            data: Subscription creation data
        """
        # Check org exists
        org = session.get(Organization, data.organization_id)
        if not org:
            raise HTTPException(
                status_code=404,
                detail=f"Organization {data.organization_id} not found"
            )

        # Check no existing subscription
        existing = SubscriptionOperations.get_by_org(session, data.organization_id)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Organization {data.organization_id} already has a subscription"
            )

        now = datetime.utcnow()
        period_end = now + timedelta(days=30)

        subscription = Subscription(
            organization_id=data.organization_id,
            plan_tier=data.plan_tier,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=period_end,
        )

        session.add(subscription)
        session.flush()
        return subscription

    @staticmethod
    def get_by_id(
        session: Session,
        subscription_id: UUID
    ) -> Optional[Subscription]:
        """Get subscription by ID."""
        return session.get(Subscription, subscription_id)

    @staticmethod
    def get_by_org(
        session: Session,
        org_id: UUID
    ) -> Optional[Subscription]:
        """Get subscription for an organization (one-to-one)."""
        query = select(Subscription).where(Subscription.organization_id == org_id)
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_by_user(
        session: Session,
        user_id: UUID
    ) -> Optional[Subscription]:
        """Get subscription for user's primary organization.

        Users access subscriptions through their org membership.
        Returns the subscription for the first org they're an owner of,
        or first org they're a member of.
        """
        from app.domain.organization_operations import OrganizationOperations

        org = OrganizationOperations.get_primary_org_for_user(session, user_id)
        if not org:
            return None

        return SubscriptionOperations.get_by_org(session, org.id)

    @staticmethod
    def get_by_stripe_customer(
        session: Session,
        stripe_customer_id: str
    ) -> Optional[Subscription]:
        """Get subscription by Stripe customer ID."""
        query = select(Subscription).where(
            Subscription.stripe_customer_id == stripe_customer_id
        )
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_by_stripe_subscription(
        session: Session,
        stripe_subscription_id: str
    ) -> Optional[Subscription]:
        """Get subscription by Stripe subscription ID."""
        query = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def update(
        session: Session,
        subscription_id: UUID,
        data: SubscriptionUpdate
    ) -> Subscription:
        """Update subscription (partial)."""
        subscription = session.get(Subscription, subscription_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"Subscription {subscription_id} not found"
            )

        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(subscription, key, value)

        session.add(subscription)
        session.flush()
        return subscription

    @staticmethod
    def change_plan(
        session: Session,
        org_id: UUID,
        new_tier: str
    ) -> Subscription:
        """
        Change subscription plan tier.

        Validates new tier exists. Logs billing event.

        Args:
            session: Database session
            org_id: Organization ID
            new_tier: New plan tier (free, pro, team, enterprise)
        """
        if new_tier not in PLANS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid plan tier: {new_tier}"
            )

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        old_tier = subscription.plan_tier
        if old_tier == new_tier:
            return subscription  # No change needed

        # Update plan
        subscription.plan_tier = new_tier
        subscription.is_manually_assigned = False  # Clear manual flag if changing via normal flow
        subscription.manually_assigned_by = None
        subscription.manually_assigned_at = None
        subscription.manual_assignment_note = None

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        # Determine if upgrade or downgrade
        old_price = get_plan(old_tier).price_monthly_cents
        new_price = get_plan(new_tier).price_monthly_cents
        event_type = (
            BillingEventType.PLAN_UPGRADED if new_price > old_price
            else BillingEventType.PLAN_DOWNGRADED if new_price < old_price
            else BillingEventType.PLAN_CHANGED
        )

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=event_type,
            description=f"Plan changed from {old_tier} to {new_tier}",
            previous_value={"plan_tier": old_tier, "price_cents": old_price},
            new_value={"plan_tier": new_tier, "price_cents": new_price}
        )

        return subscription

    @staticmethod
    def admin_assign_plan(
        session: Session,
        org_id: UUID,
        plan_tier: str,
        admin_user_id: UUID,
        note: str | None = None
    ) -> Subscription:
        """
        Manually assign plan tier (admin override).

        Used for custom deals, support cases, etc.

        Args:
            session: Database session
            org_id: Organization ID
            plan_tier: Plan tier to assign
            admin_user_id: Admin performing the assignment
            note: Reason for manual assignment
        """
        if plan_tier not in PLANS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid plan tier: {plan_tier}"
            )

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        old_tier = subscription.plan_tier
        now = datetime.utcnow()

        subscription.plan_tier = plan_tier
        subscription.is_manually_assigned = True
        subscription.manually_assigned_by = admin_user_id
        subscription.manually_assigned_at = now
        subscription.manual_assignment_note = note

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.MANUAL_ASSIGNMENT,
            description=f"Admin assigned plan {plan_tier}" + (f": {note}" if note else ""),
            previous_value={"plan_tier": old_tier},
            new_value={
                "plan_tier": plan_tier,
                "is_manually_assigned": True,
                "note": note
            },
            actor_user_id=admin_user_id
        )

        return subscription

    @staticmethod
    def set_spending_cap(
        session: Session,
        org_id: UUID,
        cap_cents: int
    ) -> Subscription:
        """
        Set spending cap for subscription.

        Args:
            session: Database session
            org_id: Organization ID
            cap_cents: Spending cap in cents (-1 = no cap)
        """
        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        old_cap = subscription.spending_cap_cents
        subscription.spending_cap_cents = cap_cents

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.SPENDING_CAP_SET,
            description=f"Spending cap set to ${cap_cents / 100:.2f}" if cap_cents >= 0 else "Spending cap removed",
            previous_value={"spending_cap_cents": old_cap},
            new_value={"spending_cap_cents": cap_cents}
        )

        return subscription

    @staticmethod
    def set_stripe_ids(
        session: Session,
        org_id: UUID,
        stripe_customer_id: str,
        stripe_subscription_id: str | None = None,
        stripe_metered_item_id: str | None = None
    ) -> Subscription:
        """Set Stripe integration IDs."""
        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        subscription.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id:
            subscription.stripe_subscription_id = stripe_subscription_id
        if stripe_metered_item_id:
            subscription.stripe_metered_item_id = stripe_metered_item_id

        session.add(subscription)
        session.flush()
        return subscription

    @staticmethod
    def set_byok_flag(
        session: Session,
        org_id: UUID,
        provider: str,
        is_set: bool
    ) -> Subscription:
        """Update BYOK key status flag.

        Args:
            session: Database session
            org_id: Organization ID
            provider: "openai" or "anthropic"
            is_set: Whether key is set
        """
        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        if provider == "openai":
            subscription.byok_openai_key_set = is_set
        elif provider == "anthropic":
            subscription.byok_anthropic_key_set = is_set
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid BYOK provider: {provider}"
            )

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        event_type = BillingEventType.BYOK_KEY_SET if is_set else BillingEventType.BYOK_KEY_REMOVED
        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=event_type,
            description=f"BYOK {provider} key {'set' if is_set else 'removed'}",
            new_value={"provider": provider, "is_set": is_set}
        )

        return subscription

    @staticmethod
    def cancel(
        session: Session,
        org_id: UUID,
        at_period_end: bool = True
    ) -> Subscription:
        """
        Cancel subscription.

        Args:
            session: Database session
            org_id: Organization ID
            at_period_end: If True, cancel at end of billing period
        """
        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        if at_period_end:
            subscription.cancel_at_period_end = True
        else:
            subscription.status = SubscriptionStatus.CANCELED
            subscription.cancel_at_period_end = False

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.SUBSCRIPTION_CANCELED,
            description="Subscription canceled" + (" at period end" if at_period_end else " immediately"),
            new_value={
                "cancel_at_period_end": at_period_end,
                "status": subscription.status
            }
        )

        return subscription

    @staticmethod
    def renew_period(
        session: Session,
        org_id: UUID
    ) -> Subscription:
        """
        Renew subscription period (called on successful payment).

        Advances billing period by 1 month.
        """
        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription:
            raise HTTPException(
                status_code=404,
                detail=f"No subscription found for organization {org_id}"
            )

        now = datetime.utcnow()
        new_period_end = now + timedelta(days=30)

        subscription.current_period_start = now
        subscription.current_period_end = new_period_end
        subscription.status = SubscriptionStatus.ACTIVE

        # Clear cancellation flag if renewing
        if subscription.cancel_at_period_end:
            subscription.cancel_at_period_end = False

        session.add(subscription)
        session.flush()

        # Log billing event
        from app.domain.billing_event_operations import BillingEventOperations
        from app.models.database.billing import BillingEventType

        BillingEventOperations.log_event(
            session,
            org_id=org_id,
            event_type=BillingEventType.PERIOD_STARTED,
            description=f"New billing period started",
            new_value={
                "period_start": now.isoformat(),
                "period_end": new_period_end.isoformat()
            }
        )

        return subscription

    @staticmethod
    def get_all_active(
        session: Session,
        limit: int = 100,
        offset: int = 0
    ) -> list[Subscription]:
        """Get all active subscriptions (for batch operations)."""
        query = (
            select(Subscription)
            .where(Subscription.status == SubscriptionStatus.ACTIVE)
            .order_by(Subscription.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = session.execute(query)
        return list(result.scalars().all())
