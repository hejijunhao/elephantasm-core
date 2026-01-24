"""Subscription API endpoints.

Pattern: Async routes + Sync domain operations + RLS filtering.
FastAPI automatically runs sync code in thread pool.
"""

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.api.deps import SubscriptionContext, get_subscription_context
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.billing_event_operations import BillingEventOperations
from app.domain.limit_operations import LimitOperations
from app.domain.usage_operations import UsageOperations
from app.config.plans import get_plan
from app.models.database.subscription import (
    SubscriptionRead,
    SpendingCapUpdate,
)
from app.models.database.billing import BillingEventRead
from app.models.database.usage import (
    UsageSummaryRead,
    LimitStatusRead,
    PlanLimitsSummaryRead,
)


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get(
    "/me",
    response_model=SubscriptionRead,
    summary="Get my subscription"
)
async def get_my_subscription(
    ctx: SubscriptionContext = Depends(get_subscription_context)
) -> SubscriptionRead:
    """
    Get current user's subscription.

    Returns the subscription for the user's primary organization.
    Includes plan tier, status, billing period, and BYOK flags.
    """
    return SubscriptionRead.model_validate(ctx.subscription)


@router.get(
    "/usage",
    response_model=UsageSummaryRead,
    summary="Get my usage summary"
)
async def get_my_usage(
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls)
) -> UsageSummaryRead:
    """
    Get current usage vs limits summary.

    Returns current usage counts, limits, overage info, and spending cap status.
    Refreshes anima counts on each request for accuracy.
    """
    # Refresh anima counts for accurate active/dormant counts
    UsageOperations.refresh_anima_counts(db, ctx.org_id)

    plan = ctx.plan
    # Re-fetch usage after refresh
    usage = UsageOperations.get_or_create_counter(db, ctx.org_id)
    limits = ctx.limits

    return UsageSummaryRead(
        plan_tier=plan.tier,
        period_start=usage.period_start,
        # Current usage
        events_created=usage.events_created,
        events_limit=plan.events_per_month,
        memories_stored=usage.memories_stored,
        memories_limit=plan.memories_stored,
        knowledge_items=usage.knowledge_items,
        knowledge_limit=plan.knowledge_items,
        pack_builds=usage.pack_builds,
        pack_builds_limit=plan.pack_builds_per_month,
        synthesis_runs=usage.synthesis_runs,
        synthesis_limit=plan.synthesis_per_month,
        # Anima usage
        active_anima_count=usage.active_anima_count,
        active_anima_limit=plan.active_anima_limit,
        dormant_anima_count=usage.dormant_anima_count,
        dormant_anima_limit=plan.dormant_anima_limit,
        # Overage info
        total_overage_cents=limits.total_overage_cents,
        spending_cap_cents=limits.spending_cap_cents,
        spending_cap_remaining_cents=limits.spending_cap_remaining_cents,
        is_hard_capped=limits.is_hard_capped,
    )


@router.get(
    "/limits",
    response_model=PlanLimitsSummaryRead,
    summary="Get all plan limits"
)
async def get_my_limits(
    ctx: SubscriptionContext = Depends(get_subscription_context)
) -> PlanLimitsSummaryRead:
    """
    Get detailed limit status for all resources.

    Returns each resource's current usage, limit, exceeded status,
    and overage cost if applicable.
    """
    limits = ctx.limits

    # Convert dataclass LimitStatus to Pydantic LimitStatusRead
    limits_dict = {
        name: LimitStatusRead(
            resource=status.resource,
            current=status.current,
            limit=status.limit,
            is_exceeded=status.is_exceeded,
            allows_overages=status.allows_overages,
            overage_amount=status.overage_amount,
            overage_cost_cents=status.overage_cost_cents,
        )
        for name, status in limits.limits.items()
    }

    return PlanLimitsSummaryRead(
        plan_tier=limits.plan_tier,
        limits=limits_dict,
        total_overage_cents=limits.total_overage_cents,
        spending_cap_cents=limits.spending_cap_cents,
        spending_cap_remaining_cents=limits.spending_cap_remaining_cents,
        is_hard_capped=limits.is_hard_capped,
    )


@router.patch(
    "/spending-cap",
    response_model=SubscriptionRead,
    summary="Update spending cap"
)
async def update_spending_cap(
    data: SpendingCapUpdate,
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls)
) -> SubscriptionRead:
    """
    Update spending cap for overages.

    Set to -1 for no cap (unlimited overages).
    Set to 0 to disable overages entirely.
    Set to positive value for cap in cents.

    Only available on plans that allow overages (Pro, Team, Enterprise).
    """
    subscription = SubscriptionOperations.set_spending_cap(
        db,
        ctx.org_id,
        data.spending_cap_cents
    )
    return SubscriptionRead.model_validate(subscription)


@router.get(
    "/billing-history",
    response_model=List[BillingEventRead],
    summary="Get billing history"
)
async def get_billing_history(
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls)
) -> List[BillingEventRead]:
    """
    Get billing event history.

    Returns subscription changes, payments, overages, and other billing events.
    Sorted by most recent first.
    """
    events = BillingEventOperations.get_events(
        db,
        ctx.org_id,
        limit=limit,
        offset=offset
    )
    return [BillingEventRead.model_validate(e) for e in events]


@router.get(
    "/payment-history",
    response_model=List[BillingEventRead],
    summary="Get payment history"
)
async def get_payment_history(
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls)
) -> List[BillingEventRead]:
    """
    Get payment-related events only.

    Returns successful and failed payment events.
    """
    events = BillingEventOperations.get_recent_payment_events(
        db,
        ctx.org_id,
        limit=limit
    )
    return [BillingEventRead.model_validate(e) for e in events]


@router.get(
    "/plan-history",
    response_model=List[BillingEventRead],
    summary="Get plan change history"
)
async def get_plan_history(
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls)
) -> List[BillingEventRead]:
    """
    Get plan change history.

    Returns upgrades, downgrades, and admin assignments.
    """
    events = BillingEventOperations.get_plan_change_history(
        db,
        ctx.org_id,
        limit=limit
    )
    return [BillingEventRead.model_validate(e) for e in events]
