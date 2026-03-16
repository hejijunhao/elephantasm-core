"""Domain operations for Billing Jobs — period-end billing and spending cap warnings.

Orchestrates: period snapshot → per-resource overage breakdown →
Stripe InvoiceItem creation → billing event logging.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlmodel import Session

from app.config.overages import OVERAGE_RATES
from app.core.config import settings
from app.domain.billing_event_operations import BillingEventOperations
from app.domain.limit_operations import LimitOperations
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.usage_operations import UsageOperations
from app.models.database.billing import BillingEventType
from app.models.database.subscription import Subscription, SubscriptionStatus
from app.models.database.usage import UsagePeriod
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)


class BillingJobOperations:
    """
    Billing job business logic. Static methods, sync session-based.

    Unlike standard domain ops, process_ended_periods() manages its own
    commits/rollbacks for per-subscription isolation (called from scheduler,
    not from API routes).

    CRITICAL: All methods are SYNC (no async/await).
    """

    @staticmethod
    def process_ended_periods(session: Session) -> list[dict]:
        """Find all active paid subscriptions with ended periods and process billing.

        For each ended period:
          1. Create period snapshot
          2. Bill overages via Stripe InvoiceItems
          3. Reset counters for new period

        Returns list of results per org processed.
        """
        now = datetime.now(timezone.utc)

        # Find active paid subscriptions where period has ended
        query = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.plan_tier.in_(["pro", "team", "enterprise"]),
                Subscription.current_period_end.isnot(None),
                Subscription.current_period_end <= now,
                Subscription.is_internal.is_(False),
            )
        )
        subscriptions = list(session.execute(query).scalars().all())

        if not subscriptions:
            logger.info("No ended billing periods to process")
            return []

        logger.info(f"Processing {len(subscriptions)} ended billing periods")

        results = []
        for sub in subscriptions:
            try:
                result = BillingJobOperations._process_single_period(session, sub)
                results.append(result)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(
                    f"Org {sub.organization_id}: Period billing failed — {e}",
                    exc_info=True,
                )
                results.append({
                    "org_id": str(sub.organization_id),
                    "success": False,
                    "error": str(e),
                })

        return results

    @staticmethod
    def _process_single_period(session: Session, subscription: Subscription) -> dict:
        """Process a single ended billing period for one org."""
        org_id = subscription.organization_id

        # 1. Refresh storage counts before snapshot
        UsageOperations.recount_storage(session, org_id)
        UsageOperations.refresh_anima_counts(session, org_id)

        # 2. Create period snapshot
        period = UsageOperations.create_period_snapshot(session, org_id)

        # 3. Bill overages
        billing_result = BillingJobOperations.bill_period_overages(
            session, org_id, period, subscription
        )

        # 4. Mark period as billed
        UsageOperations.mark_period_billed(session, period.id)

        # 5. Reset counters for new period
        UsageOperations.reset_counters(session, org_id)

        # 6. Advance current_period_end to prevent re-processing before Stripe webhook arrives
        #    Stripe's subscription.updated webhook will overwrite with the actual period dates.
        subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=32)
        session.add(subscription)
        session.flush()

        logger.info(
            f"Org {org_id}: Period billed — "
            f"{billing_result['items_created']} items, "
            f"${billing_result['total_billed_cents'] / 100:.2f}"
        )

        return {
            "org_id": str(org_id),
            "success": True,
            "period_id": str(period.id),
            "total_billed_cents": billing_result["total_billed_cents"],
            "items_created": billing_result["items_created"],
        }

    @staticmethod
    def bill_period_overages(
        session: Session,
        org_id: UUID,
        period: UsagePeriod,
        subscription: Subscription,
    ) -> dict:
        """Bill overages for a completed period via Stripe invoice items.

        Creates one InvoiceItem per resource type with overage.
        Returns dict with total_billed_cents and items_created.
        """
        if not subscription.stripe_customer_id:
            logger.warning(
                f"Org {org_id}: No Stripe customer — skipping overage billing"
            )
            return {"total_billed_cents": 0, "items_created": 0}

        # Get per-resource breakdown
        usage = UsageOperations.get_period_resource_usage(period)
        overages = LimitOperations.calculate_resource_overages(usage, period.plan_tier)

        if not overages:
            return {"total_billed_cents": 0, "items_created": 0}

        total_billed = 0
        items_created = 0

        for overage in overages:
            resource = overage["resource"]
            cost_cents = overage["cost_cents"]
            overage_amount = overage["overage_amount"]

            rate = OVERAGE_RATES.get(resource)
            if not rate:
                continue

            # Build human-readable description for Stripe invoice
            description = (
                f"{resource.replace('_', ' ').title()} overage: "
                f"{overage_amount:,} over limit "
                f"(${cost_cents / 100:.2f})"
            )

            try:
                product_id = settings.get_overage_product(resource)
                StripeService.create_invoice_item(
                    customer_id=subscription.stripe_customer_id,
                    amount_cents=cost_cents,
                    description=description,
                    product_id=product_id,
                    metadata={
                        "organization_id": str(org_id),
                        "period_id": str(period.id),
                        "resource": resource,
                        "usage": overage["usage"],
                        "limit": overage["limit"],
                        "overage_amount": overage_amount,
                    },
                )
                total_billed += cost_cents
                items_created += 1
            except Exception as e:
                # Log but continue — partial billing is safer than re-raising,
                # which would cause duplicate InvoiceItems on retry (Stripe items
                # can't be rolled back). Partial billing = revenue loss to us,
                # never a customer overcharge.
                logger.error(
                    f"Org {org_id}: Failed to create InvoiceItem for {resource} "
                    f"({cost_cents}¢) — {e}. This overage will NOT be billed.",
                    exc_info=True,
                )

        # Log billing event
        if total_billed > 0:
            BillingEventOperations.log_overage_billed(
                session,
                org_id=org_id,
                overage_cents=total_billed,
                details={
                    "period_id": str(period.id),
                    "items": [
                        {"resource": o["resource"], "cost_cents": o["cost_cents"]}
                        for o in overages
                    ],
                },
            )

        return {"total_billed_cents": total_billed, "items_created": items_created}

    @staticmethod
    def check_spending_cap_warnings(session: Session) -> list[dict]:
        """Check all active paid subscriptions for spending cap proximity.

        For each org where current overages >= 80% of spending cap:
          - Log OVERAGE_WARNING (if not already warned this period)
          - If >= 100%, log SPENDING_CAP_REACHED

        Returns list of warnings issued.
        """
        query = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.plan_tier.in_(["pro", "team", "enterprise"]),
                Subscription.spending_cap_cents >= 0,
                Subscription.is_internal.is_(False),
            )
        )
        subscriptions = list(session.execute(query).scalars().all())

        warnings = []
        for sub in subscriptions:
            try:
                warning = BillingJobOperations._check_single_cap(session, sub)
                if warning:
                    warnings.append(warning)
            except Exception as e:
                logger.error(
                    f"Org {sub.organization_id}: Spending cap check failed — {e}",
                    exc_info=True,
                )

        return warnings

    @staticmethod
    def _check_single_cap(session: Session, subscription: Subscription) -> dict | None:
        """Check spending cap for a single org. Returns warning dict or None."""
        org_id = subscription.organization_id
        cap = subscription.spending_cap_cents

        if cap <= 0:
            return None

        total_overage = LimitOperations.calculate_total_overage(session, org_id)
        if total_overage <= 0:
            return None

        percentage = (total_overage / cap) * 100

        # Check idempotency — don't re-warn if already warned this period
        if percentage >= 80:
            existing = BillingEventOperations.get_events_by_type(
                session, org_id, BillingEventType.OVERAGE_WARNING, limit=1
            )
            # Only warn if no warning exists, or last warning was for a different
            # percentage band, or last warning was from a previous billing period
            already_warned = False
            if existing:
                last_warn = existing[0]
                last_pct = (last_warn.new_value or {}).get("percentage", 0)
                # Different period? Always re-warn.
                period_start = subscription.current_period_start
                is_same_period = (
                    period_start
                    and last_warn.created_at >= period_start
                )
                # Same band (80-99 or 100+) in same period? Skip.
                if is_same_period and (
                    (last_pct >= 100 and percentage >= 100)
                    or (80 <= last_pct < 100 and 80 <= percentage < 100)
                ):
                    already_warned = True

            if not already_warned:
                BillingEventOperations.log_overage_warning(
                    session, org_id, total_overage, cap
                )
                session.flush()

                level = "reached" if percentage >= 100 else "warning"
                logger.info(
                    f"Org {org_id}: Spending cap {level} — "
                    f"{percentage:.0f}% (${total_overage / 100:.2f} / ${cap / 100:.2f})"
                )
                return {
                    "org_id": str(org_id),
                    "percentage": percentage,
                    "overage_cents": total_overage,
                    "cap_cents": cap,
                    "level": level,
                }

        return None
