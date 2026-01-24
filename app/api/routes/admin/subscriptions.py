"""Admin Subscription API endpoints.

Pattern: Async routes + Sync domain operations.
Requires admin authentication (email in ADMIN_EMAILS config).
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import require_current_user_id
from app.core.config import settings
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.organization_operations import OrganizationOperations
from app.domain.billing_event_operations import BillingEventOperations
from app.domain.usage_operations import UsageOperations
from app.domain.limit_operations import LimitOperations
from app.models.database.subscription import SubscriptionRead, AdminPlanAssignment
from app.models.database.usage import PlanLimitsSummaryRead, LimitStatusRead
from app.models.database.user import User


router = APIRouter(prefix="/admin/subscriptions", tags=["admin-subscriptions"])


async def require_admin(
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db)
) -> UUID:
    """
    Require admin access.

    Checks if user's email is in ADMIN_EMAILS config.

    Raises:
        HTTPException 403: If user is not an admin
    """
    user = db.get(User, user_id)
    if not user or not user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    if user.email.lower() not in [e.lower() for e in settings.ADMIN_EMAILS]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    return user_id


class SubscriptionWithOrg(SubscriptionRead):
    """Subscription with organization name for admin views."""
    organization_name: str
    organization_slug: str


class AdminSubscriptionSummary(BaseModel):
    """Summary of a subscription for admin list view."""
    id: UUID
    organization_id: UUID
    organization_name: str
    organization_slug: str
    plan_tier: str
    status: str
    is_manually_assigned: bool
    total_overage_cents: int
    is_hard_capped: bool


@router.get(
    "",
    response_model=List[AdminSubscriptionSummary],
    summary="List all subscriptions (admin)"
)
async def list_subscriptions(
    plan_tier: Optional[str] = Query(None, description="Filter by plan tier"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    admin_id: UUID = Depends(require_admin),
    db: Session = Depends(get_db)
) -> List[AdminSubscriptionSummary]:
    """
    List all subscriptions with organization info.

    Admin only endpoint. Returns subscriptions across all organizations.
    """
    from sqlalchemy import select
    from app.models.database.subscription import Subscription
    from app.models.database.organization import Organization

    # Build query
    query = (
        select(Subscription, Organization)
        .join(Organization, Subscription.organization_id == Organization.id)
    )

    if plan_tier:
        query = query.where(Subscription.plan_tier == plan_tier)

    if status_filter:
        query = query.where(Subscription.status == status_filter)

    query = (
        query
        .order_by(Subscription.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = db.execute(query)
    rows = result.all()

    summaries = []
    for sub, org in rows:
        # Get limits for overage info
        limits = LimitOperations.get_all_limits(db, org.id)

        summaries.append(AdminSubscriptionSummary(
            id=sub.id,
            organization_id=org.id,
            organization_name=org.name,
            organization_slug=org.slug,
            plan_tier=sub.plan_tier,
            status=sub.status,
            is_manually_assigned=sub.is_manually_assigned,
            total_overage_cents=limits.total_overage_cents,
            is_hard_capped=limits.is_hard_capped,
        ))

    return summaries


@router.get(
    "/by-org/{org_id}",
    response_model=SubscriptionWithOrg,
    summary="Get subscription by org (admin)"
)
async def get_subscription_by_org(
    org_id: UUID,
    admin_id: UUID = Depends(require_admin),
    db: Session = Depends(get_db)
) -> SubscriptionWithOrg:
    """
    Get subscription for specific organization.

    Admin only endpoint.
    """
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found"
        )

    subscription = SubscriptionOperations.get_by_org(db, org_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No subscription for organization {org_id}"
        )

    # Manually construct response with org info
    sub_dict = SubscriptionRead.model_validate(subscription).model_dump()
    sub_dict["organization_name"] = org.name
    sub_dict["organization_slug"] = org.slug

    return SubscriptionWithOrg(**sub_dict)


@router.get(
    "/by-user/{user_id}",
    response_model=SubscriptionWithOrg,
    summary="Get subscription by user (admin)"
)
async def get_subscription_by_user(
    user_id: UUID,
    admin_id: UUID = Depends(require_admin),
    db: Session = Depends(get_db)
) -> SubscriptionWithOrg:
    """
    Get subscription for specific user's primary org.

    Admin only endpoint.
    """
    from app.models.database.organization import Organization

    org = OrganizationOperations.get_primary_org_for_user(db, user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No organization found for user {user_id}"
        )

    subscription = SubscriptionOperations.get_by_org(db, org.id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No subscription for user {user_id}"
        )

    sub_dict = SubscriptionRead.model_validate(subscription).model_dump()
    sub_dict["organization_name"] = org.name
    sub_dict["organization_slug"] = org.slug

    return SubscriptionWithOrg(**sub_dict)


@router.post(
    "/by-org/{org_id}/assign-plan",
    response_model=SubscriptionRead,
    summary="Assign plan (admin)"
)
async def admin_assign_plan(
    org_id: UUID,
    data: AdminPlanAssignment,
    admin_id: UUID = Depends(require_admin),
    db: Session = Depends(get_db)
) -> SubscriptionRead:
    """
    Manually assign a plan to an organization.

    Admin only endpoint. Bypasses normal billing flow.
    Creates audit trail with admin's user ID.
    """
    subscription = SubscriptionOperations.admin_assign_plan(
        db,
        org_id=org_id,
        plan_tier=data.plan_tier,
        admin_user_id=admin_id,
        note=data.note
    )
    return SubscriptionRead.model_validate(subscription)


@router.get(
    "/by-org/{org_id}/limits",
    response_model=PlanLimitsSummaryRead,
    summary="Get org limits (admin)"
)
async def get_org_limits(
    org_id: UUID,
    admin_id: UUID = Depends(require_admin),
    db: Session = Depends(get_db)
) -> PlanLimitsSummaryRead:
    """
    Get detailed limit status for an organization.

    Admin only endpoint.
    """
    from app.models.database.organization import Organization

    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {org_id} not found"
        )

    limits = LimitOperations.get_all_limits(db, org_id)

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


# Import Organization model at module level for type checking
from app.models.database.organization import Organization
