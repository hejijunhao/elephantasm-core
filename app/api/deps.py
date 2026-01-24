"""API dependencies for subscription context, feature gating, and action limits.

Provides FastAPI dependencies for:
- SubscriptionContext: Bundles user, subscription, plan, usage, limits
- FeatureGate: Blocks access to features not in plan
- RequireActionAllowed: Blocks/logs when limits exceeded
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.core.auth import require_current_user_id
from app.config.plans import PlanConfig, get_plan
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.organization_operations import OrganizationOperations, OrganizationMemberOperations
from app.domain.usage_operations import UsageOperations
from app.domain.limit_operations import LimitOperations, PlanLimitsSummary
from app.models.database.subscription import Subscription
from app.models.database.usage import UsageCounter
from app.models.database.user import User


@dataclass
class SubscriptionContext:
    """Bundled subscription context for authenticated requests.

    Contains all subscription-related info needed by routes:
    - user_id: Current user's UUID
    - org_id: User's primary organization UUID
    - subscription: Subscription record (or None if missing)
    - plan: Plan configuration (defaults to free)
    - usage: Current usage counters
    - limits: All limit statuses
    """
    user_id: UUID
    org_id: UUID
    subscription: Optional[Subscription]
    plan: PlanConfig
    usage: UsageCounter
    limits: PlanLimitsSummary


async def get_subscription_context(
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
) -> SubscriptionContext:
    """
    Get full subscription context for authenticated user.

    Bundles user, org, subscription, plan, usage, and limits into
    a single dependency for convenient access in routes.

    Supports org switching via X-Organization-Id header.
    Auto-creates missing subscription (shouldn't happen with trigger).

    Args:
        user_id: Current user ID (from JWT/API key)
        db: Database session with RLS context
        x_organization_id: Optional org ID header for org switching

    Returns:
        SubscriptionContext with all subscription info

    Raises:
        HTTPException 404: If user has no organization
        HTTPException 403: If user not member of specified org
    """
    # Check for org override via header
    if x_organization_id:
        try:
            org_id = UUID(x_organization_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Organization-Id header format"
            )

        # Verify user is member of this org
        if not OrganizationMemberOperations.is_member(db, org_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of the specified organization"
            )

        org = OrganizationOperations.get_by_id(db, org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    else:
        # Get user's primary organization
        org = OrganizationOperations.get_primary_org_for_user(db, user_id)

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found for user. Contact support."
        )

    # Get or create subscription (shouldn't need to create with auto-provisioning)
    subscription = SubscriptionOperations.get_by_org(db, org.id)
    if not subscription:
        # Auto-create free subscription if missing (edge case)
        from app.models.database.subscription import SubscriptionCreate
        subscription = SubscriptionOperations.create(
            db,
            SubscriptionCreate(organization_id=org.id, plan_tier="free")
        )

    # Get plan config
    plan = get_plan(subscription.plan_tier)

    # Get or create usage counter
    usage = UsageOperations.get_or_create_counter(db, org.id)

    # Get all limits
    limits = LimitOperations.get_all_limits(db, org.id)

    return SubscriptionContext(
        user_id=user_id,
        org_id=org.id,
        subscription=subscription,
        plan=plan,
        usage=usage,
        limits=limits
    )


class FeatureGate:
    """
    Dependency that blocks access to features not included in plan.

    Usage:
        @router.post("/dreamer/trigger")
        async def trigger_dreamer(
            _: bool = Depends(FeatureGate("dreamer_enabled")),
            ctx: SubscriptionContext = Depends(get_subscription_context)
        ):
            ...

    Features:
        - dreamer_enabled: Access to Dreamer curation
        - byok_enabled: Bring Your Own Key
        - audit_logs_enabled: Access to audit logs
    """

    def __init__(self, feature: str):
        """
        Args:
            feature: Feature attribute name from PlanConfig
        """
        self.feature = feature

    async def __call__(
        self,
        ctx: SubscriptionContext = Depends(get_subscription_context)
    ) -> bool:
        """
        Check if feature is available on user's plan.

        Raises:
            HTTPException 403: If feature not available
        """
        has_feature = getattr(ctx.plan, self.feature, False)

        if not has_feature:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "feature_not_available",
                    "feature": self.feature,
                    "current_plan": ctx.plan.display_name,
                    "current_tier": ctx.plan.tier,
                    "message": f"'{self.feature}' requires a higher plan.",
                    "upgrade_url": "/settings/billing"
                }
            )

        return True


class RequireActionAllowed:
    """
    Dependency that blocks actions when limits exceeded (free tier)
    or allows with overage logging (paid tiers).

    Usage:
        @router.post("/animas")
        async def create_anima(
            ctx: SubscriptionContext = Depends(RequireActionAllowed("create_anima"))
        ):
            ...

    Actions:
        - create_anima: Check active anima limit
        - create_event: Check event limit
        - synthesis: Check synthesis limit
        - pack_build: Check pack build limit
    """

    def __init__(self, action: str):
        """
        Args:
            action: Action name for limit checking
        """
        self.action = action

    async def __call__(
        self,
        user_id: UUID = Depends(require_current_user_id),
        db: Session = Depends(get_db_with_rls)
    ) -> SubscriptionContext:
        """
        Check if action is allowed, return subscription context.

        For free tier: Blocks if limit exceeded
        For paid tiers: Allows with overage (unless spending cap reached)

        Returns:
            SubscriptionContext if action allowed

        Raises:
            HTTPException 403: If action blocked by limits
        """
        # Get user's organization
        org = OrganizationOperations.get_primary_org_for_user(db, user_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No organization found for user. Contact support."
            )

        # Check if action is allowed
        allowed, error = LimitOperations.is_action_allowed(db, org.id, self.action)

        if not allowed:
            # Get plan info for error response
            subscription = SubscriptionOperations.get_by_org(db, org.id)
            plan = get_plan(subscription.plan_tier if subscription else "free")

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "limit_exceeded",
                    "action": self.action,
                    "current_plan": plan.display_name,
                    "current_tier": plan.tier,
                    "message": error,
                    "upgrade_url": "/settings/billing"
                }
            )

        # Build and return subscription context
        subscription = SubscriptionOperations.get_by_org(db, org.id)
        plan = get_plan(subscription.plan_tier if subscription else "free")
        usage = UsageOperations.get_or_create_counter(db, org.id)
        limits = LimitOperations.get_all_limits(db, org.id)

        return SubscriptionContext(
            user_id=user_id,
            org_id=org.id,
            subscription=subscription,
            plan=plan,
            usage=usage,
            limits=limits
        )


# Convenience dependency for routes that need user's organization
async def get_user_org_id(
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> UUID:
    """
    Get user's primary organization ID.

    Raises:
        HTTPException 404: If user has no organization
    """
    org = OrganizationOperations.get_primary_org_for_user(db, user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found for user. Contact support."
        )
    return org.id
