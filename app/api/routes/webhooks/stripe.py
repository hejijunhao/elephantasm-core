"""Stripe webhook handler — processes subscription lifecycle events.

This route is UNAUTHENTICATED (no JWT/API key). Stripe signs payloads
with HMAC via the stripe-signature header; we verify using the webhook secret.

Idempotency: Each handler checks BillingEventOperations.get_by_stripe_event()
before processing to prevent duplicate billing events on redelivery.
"""

import logging
from uuid import UUID

import stripe
from fastapi import APIRouter, Request, HTTPException

from app.core.config import settings
from app.core.database import get_db_session
from app.domain.billing_event_operations import BillingEventOperations
from app.domain.subscription_operations import SubscriptionOperations
from app.models.database.billing import BillingEventType
from app.services.stripe_service import StripeService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(400, "Missing stripe-signature header")

    try:
        event = StripeService.construct_webhook_event(payload, sig_header)
    except ValueError:
        raise HTTPException(400, "Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")

    logger.info(f"Stripe webhook received: {event.type} ({event.id})")

    with get_db_session() as db:
        _handle_stripe_event(db, event)

    return {"status": "success"}


def _handle_stripe_event(db, event: stripe.Event):
    """Route event to appropriate handler."""
    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.created": _handle_invoice_created,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
    }

    handler = handlers.get(event.type)
    if handler:
        handler(db, event)
    else:
        logger.info(f"Unhandled Stripe event type: {event.type}")


def _handle_checkout_completed(db, event: stripe.Event):
    """Handle successful checkout — activate subscription."""
    session_obj = event.data.object
    org_id_str = session_obj.metadata.get("organization_id")
    if not org_id_str:
        logger.warning(f"checkout.session.completed missing organization_id metadata: {event.id}")
        return

    # Idempotency check
    if BillingEventOperations.get_by_stripe_event(db, event.id):
        logger.info(f"Duplicate webhook skipped: {event.id}")
        return

    org_id = UUID(org_id_str)
    subscription_id = session_obj.subscription
    customer_id = session_obj.customer

    # Retrieve full subscription from Stripe for period dates + price
    stripe_sub = stripe.Subscription.retrieve(subscription_id)
    plan_tier = _get_tier_from_price(stripe_sub.items.data[0].price.id)

    SubscriptionOperations.update_from_stripe(
        db,
        org_id,
        plan_tier=plan_tier,
        stripe_subscription_id=subscription_id,
        stripe_customer_id=customer_id,
        status="active",
        cancel_at_period_end=False,
        current_period_start=stripe_sub.current_period_start,
        current_period_end=stripe_sub.current_period_end,
    )

    BillingEventOperations.log_event(
        db,
        org_id=org_id,
        event_type=BillingEventType.PLAN_UPGRADED,
        description=f"Upgraded to {plan_tier} via Stripe Checkout",
        new_value={"plan_tier": plan_tier, "stripe_subscription_id": subscription_id},
        stripe_event_id=event.id,
    )

    logger.info(f"Checkout completed: org {org_id} -> {plan_tier}")


def _handle_subscription_updated(db, event: stripe.Event):
    """Handle subscription changes (plan change, renewal, cancellation toggle)."""
    subscription_obj = event.data.object
    org_id_str = subscription_obj.metadata.get("organization_id")
    if not org_id_str:
        logger.warning(f"customer.subscription.updated missing organization_id metadata: {event.id}")
        return

    if BillingEventOperations.get_by_stripe_event(db, event.id):
        logger.info(f"Duplicate webhook skipped: {event.id}")
        return

    org_id = UUID(org_id_str)
    plan_tier = _get_tier_from_price(subscription_obj.items.data[0].price.id)

    SubscriptionOperations.update_from_stripe(
        db,
        org_id,
        plan_tier=plan_tier,
        status=subscription_obj.status,
        cancel_at_period_end=subscription_obj.cancel_at_period_end,
        current_period_start=subscription_obj.current_period_start,
        current_period_end=subscription_obj.current_period_end,
    )

    BillingEventOperations.log_event(
        db,
        org_id=org_id,
        event_type=BillingEventType.PLAN_CHANGED,
        description=f"Subscription updated: {plan_tier} (status: {subscription_obj.status})",
        new_value={
            "plan_tier": plan_tier,
            "status": subscription_obj.status,
            "cancel_at_period_end": subscription_obj.cancel_at_period_end,
        },
        stripe_event_id=event.id,
    )

    logger.info(f"Subscription updated: org {org_id} -> {plan_tier} ({subscription_obj.status})")


def _handle_subscription_deleted(db, event: stripe.Event):
    """Handle subscription cancellation — revert to free tier."""
    subscription_obj = event.data.object
    org_id_str = subscription_obj.metadata.get("organization_id")
    if not org_id_str:
        logger.warning(f"customer.subscription.deleted missing organization_id metadata: {event.id}")
        return

    if BillingEventOperations.get_by_stripe_event(db, event.id):
        logger.info(f"Duplicate webhook skipped: {event.id}")
        return

    org_id = UUID(org_id_str)

    SubscriptionOperations.update_from_stripe(
        db,
        org_id,
        plan_tier="free",
        status="canceled",
        stripe_subscription_id=None,
    )

    BillingEventOperations.log_event(
        db,
        org_id=org_id,
        event_type=BillingEventType.SUBSCRIPTION_CANCELED,
        description="Subscription canceled, reverted to Free tier",
        stripe_event_id=event.id,
    )

    logger.info(f"Subscription deleted: org {org_id} -> free")


def _handle_invoice_created(db, event: stripe.Event):
    """Log when an invoice is created with overage line items (informational)."""
    invoice = event.data.object
    if not invoice.subscription:
        return

    line_count = len(invoice.lines.data) if invoice.lines else 0
    if line_count > 1:
        logger.info(
            f"Invoice created with {line_count} line items, "
            f"total: ${(invoice.amount_due or 0) / 100:.2f} ({event.id})"
        )


def _handle_invoice_paid(db, event: stripe.Event):
    """Handle successful payment."""
    invoice = event.data.object

    # Get org_id from subscription metadata
    org_id_str = None
    if invoice.subscription:
        try:
            stripe_sub = stripe.Subscription.retrieve(invoice.subscription)
            org_id_str = stripe_sub.metadata.get("organization_id")
        except Exception:
            logger.warning(f"Could not retrieve subscription for invoice {invoice.id}")

    if not org_id_str:
        logger.info(f"invoice.paid without org context, skipping: {event.id}")
        return

    if BillingEventOperations.get_by_stripe_event(db, event.id):
        logger.info(f"Duplicate webhook skipped: {event.id}")
        return

    org_id = UUID(org_id_str)
    amount_cents = invoice.amount_paid or 0

    BillingEventOperations.log_payment_succeeded(
        db,
        org_id=org_id,
        amount_cents=amount_cents,
        stripe_event_id=event.id,
    )

    logger.info(f"Invoice paid: org {org_id}, ${amount_cents / 100:.2f}")


def _handle_payment_failed(db, event: stripe.Event):
    """Handle failed payment — mark subscription as past_due."""
    invoice = event.data.object

    org_id_str = None
    if invoice.subscription:
        try:
            stripe_sub = stripe.Subscription.retrieve(invoice.subscription)
            org_id_str = stripe_sub.metadata.get("organization_id")
        except Exception:
            logger.warning(f"Could not retrieve subscription for invoice {invoice.id}")

    if not org_id_str:
        logger.info(f"invoice.payment_failed without org context, skipping: {event.id}")
        return

    if BillingEventOperations.get_by_stripe_event(db, event.id):
        logger.info(f"Duplicate webhook skipped: {event.id}")
        return

    org_id = UUID(org_id_str)

    SubscriptionOperations.update_from_stripe(db, org_id, status="past_due")

    amount_cents = invoice.amount_due or 0
    BillingEventOperations.log_payment_failed(
        db,
        org_id=org_id,
        amount_cents=amount_cents,
        stripe_event_id=event.id,
    )

    logger.info(f"Payment failed: org {org_id}, ${amount_cents / 100:.2f}")


def _get_tier_from_price(price_id: str) -> str:
    """Map Stripe price ID to plan tier."""
    price_map = {
        settings.STRIPE_PRICE_PRO: "pro",
        settings.STRIPE_PRICE_TEAM: "team",
    }
    tier = price_map.get(price_id)
    if not tier:
        logger.warning(f"Unknown Stripe price ID: {price_id}, defaulting to free")
        return "free"
    return tier
