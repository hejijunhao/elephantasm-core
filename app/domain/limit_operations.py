"""Domain operations for Limit checking - plan limits and overage calculation.

Business logic for checking usage against plan limits and calculating overages.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session

from app.config.plans import get_plan, PlanConfig
from app.config.overages import calculate_overage_cost, OVERAGE_RATES


@dataclass
class LimitStatus:
    """Status of a single resource limit."""
    resource: str
    current: int
    limit: int
    is_exceeded: bool
    allows_overages: bool
    overage_amount: int
    overage_cost_cents: int


@dataclass
class PlanLimitsSummary:
    """Summary of all plan limits and current usage."""
    plan_tier: str
    limits: dict[str, LimitStatus]
    total_overage_cents: int
    spending_cap_cents: int
    spending_cap_remaining_cents: int
    is_hard_capped: bool  # True if free tier and any limit exceeded


class LimitOperations:
    """
    Limit checking business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def check_limit(
        current: int,
        limit: int,
        resource: str,
        allows_overages: bool,
        plan_tier: str
    ) -> LimitStatus:
        """
        Check a single resource limit.

        Args:
            current: Current usage count
            limit: Plan limit (-1 = unlimited)
            resource: Resource name (for overage calculation)
            allows_overages: Whether plan allows overages
            plan_tier: Plan tier (for overage pricing)

        Returns:
            LimitStatus with all relevant info
        """
        # Unlimited
        if limit == -1:
            return LimitStatus(
                resource=resource,
                current=current,
                limit=limit,
                is_exceeded=False,
                allows_overages=allows_overages,
                overage_amount=0,
                overage_cost_cents=0
            )

        is_exceeded = current > limit
        overage_amount = max(0, current - limit)
        overage_cost_cents = 0

        if is_exceeded and allows_overages:
            overage_cost_cents = calculate_overage_cost(
                resource=resource,
                usage=current,
                limit=limit,
                plan_tier=plan_tier
            )

        return LimitStatus(
            resource=resource,
            current=current,
            limit=limit,
            is_exceeded=is_exceeded,
            allows_overages=allows_overages,
            overage_amount=overage_amount,
            overage_cost_cents=overage_cost_cents
        )

    @staticmethod
    def check_anima_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check active anima limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.active_anima_count,
            limit=plan.active_anima_limit,
            resource="active_animas",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def check_event_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check events per month limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.events_created,
            limit=plan.events_per_month,
            resource="events",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def check_memory_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check memories stored limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.memories_stored,
            limit=plan.memories_stored,
            resource="memories",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def check_knowledge_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check knowledge items limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.knowledge_items,
            limit=plan.knowledge_items,
            resource="knowledge",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def check_pack_build_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check pack builds per month limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.pack_builds,
            limit=plan.pack_builds_per_month,
            resource="pack_builds",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def check_synthesis_limit(
        session: Session,
        org_id: UUID
    ) -> LimitStatus:
        """Check synthesis runs per month limit for organization."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        counter = UsageOperations.get_or_create_counter(session, org_id)

        return LimitOperations.check_limit(
            current=counter.synthesis_runs,
            limit=plan.synthesis_per_month,
            resource="synthesis",
            allows_overages=plan.allows_overages,
            plan_tier=plan.tier
        )

    @staticmethod
    def get_all_limits(
        session: Session,
        org_id: UUID
    ) -> PlanLimitsSummary:
        """Get summary of all plan limits and current usage."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")
        counter = UsageOperations.get_or_create_counter(session, org_id)

        # Build all limit statuses
        limits = {
            "active_animas": LimitOperations.check_limit(
                counter.active_anima_count, plan.active_anima_limit,
                "active_animas", plan.allows_overages, plan.tier
            ),
            "dormant_animas": LimitOperations.check_limit(
                counter.dormant_anima_count, plan.dormant_anima_limit,
                "dormant_animas", plan.allows_overages, plan.tier
            ),
            "events": LimitOperations.check_limit(
                counter.events_created, plan.events_per_month,
                "events", plan.allows_overages, plan.tier
            ),
            "memories": LimitOperations.check_limit(
                counter.memories_stored, plan.memories_stored,
                "memories", plan.allows_overages, plan.tier
            ),
            "knowledge": LimitOperations.check_limit(
                counter.knowledge_items, plan.knowledge_items,
                "knowledge", plan.allows_overages, plan.tier
            ),
            "pack_builds": LimitOperations.check_limit(
                counter.pack_builds, plan.pack_builds_per_month,
                "pack_builds", plan.allows_overages, plan.tier
            ),
            "synthesis": LimitOperations.check_limit(
                counter.synthesis_runs, plan.synthesis_per_month,
                "synthesis", plan.allows_overages, plan.tier
            ),
        }

        # Calculate total overage
        total_overage_cents = sum(l.overage_cost_cents for l in limits.values())

        # Spending cap handling
        spending_cap_cents = subscription.spending_cap_cents if subscription else -1
        if spending_cap_cents == -1:
            spending_cap_remaining_cents = -1  # No cap
        else:
            spending_cap_remaining_cents = max(0, spending_cap_cents - total_overage_cents)

        # Is hard capped (free tier with any limit exceeded)
        is_hard_capped = (
            not plan.allows_overages and
            any(l.is_exceeded for l in limits.values())
        )

        return PlanLimitsSummary(
            plan_tier=plan.tier,
            limits=limits,
            total_overage_cents=total_overage_cents,
            spending_cap_cents=spending_cap_cents,
            spending_cap_remaining_cents=spending_cap_remaining_cents,
            is_hard_capped=is_hard_capped
        )

    @staticmethod
    def is_action_allowed(
        session: Session,
        org_id: UUID,
        action: str
    ) -> tuple[bool, str | None]:
        """
        Check if an action is allowed based on limits.

        Actions:
        - create_anima: Check active anima limit
        - create_event: Check event limit
        - synthesis: Check synthesis limit
        - pack_build: Check pack build limit

        Returns:
            (allowed, error_message) - error_message is None if allowed
        """
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        # Check spending cap first
        if subscription and subscription.spending_cap_cents >= 0:
            summary = LimitOperations.get_all_limits(session, org_id)
            if summary.total_overage_cents >= subscription.spending_cap_cents:
                return (False, f"Spending cap of ${subscription.spending_cap_cents / 100:.2f} reached. Increase cap or upgrade plan.")

        # Check specific action
        if action == "create_anima":
            status = LimitOperations.check_anima_limit(session, org_id)
            if status.is_exceeded and not plan.allows_overages:
                return (False, f"Active anima limit of {status.limit} reached. Upgrade to create more animas.")

        elif action == "create_event":
            status = LimitOperations.check_event_limit(session, org_id)
            if status.is_exceeded and not plan.allows_overages:
                return (False, f"Monthly event limit of {status.limit:,} reached. Upgrade to continue.")

        elif action == "synthesis":
            status = LimitOperations.check_synthesis_limit(session, org_id)
            if status.is_exceeded and not plan.allows_overages:
                return (False, f"Monthly synthesis limit of {status.limit:,} reached. Upgrade to continue.")

        elif action == "pack_build":
            status = LimitOperations.check_pack_build_limit(session, org_id)
            if status.is_exceeded and not plan.allows_overages:
                return (False, f"Monthly pack build limit of {status.limit:,} reached. Upgrade to continue.")

        else:
            # Unknown action - allow by default
            pass

        return (True, None)

    @staticmethod
    def calculate_total_overage(
        session: Session,
        org_id: UUID
    ) -> int:
        """Calculate total overage cost in cents for current period."""
        summary = LimitOperations.get_all_limits(session, org_id)
        return summary.total_overage_cents

    @staticmethod
    def check_spending_cap_warning(
        session: Session,
        org_id: UUID
    ) -> tuple[bool, float]:
        """
        Check if spending cap warning threshold reached.

        Returns:
            (should_warn, percentage) - percentage of cap used
        """
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        if not subscription or subscription.spending_cap_cents < 0:
            return (False, 0.0)

        summary = LimitOperations.get_all_limits(session, org_id)
        cap = subscription.spending_cap_cents

        if cap == 0:
            return (False, 0.0)

        percentage = (summary.total_overage_cents / cap) * 100

        # Warn at 80%
        should_warn = percentage >= 80

        return (should_warn, percentage)

    @staticmethod
    def get_plan_feature(
        session: Session,
        org_id: UUID,
        feature: str
    ) -> bool:
        """
        Check if a feature is available on the organization's plan.

        Features:
        - dreamer_enabled
        - byok_enabled
        - audit_logs_enabled

        Returns:
            True if feature is available
        """
        from app.domain.subscription_operations import SubscriptionOperations

        subscription = SubscriptionOperations.get_by_org(session, org_id)
        plan = get_plan(subscription.plan_tier if subscription else "free")

        return getattr(plan, feature, False)
