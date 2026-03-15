"""Stripe API wrapper for subscription management.

Handles customer creation, checkout sessions, customer portal,
and webhook event verification. All methods are static and sync.
"""

import logging

import stripe

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)


class StripeService:
    """Stripe API operations. Static methods wrapping the Stripe SDK."""

    @staticmethod
    def create_customer(email: str, name: str, org_id: str) -> str:
        """Create Stripe customer, return customer_id."""
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"organization_id": org_id},
        )
        logger.info(f"Created Stripe customer {customer.id} for org {org_id}")
        return customer.id

    @staticmethod
    def create_checkout_session(
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        org_id: str,
    ) -> str:
        """Create Checkout Session, return session URL."""
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"organization_id": org_id},
            subscription_data={"metadata": {"organization_id": org_id}},
        )
        return session.url

    @staticmethod
    def create_portal_session(customer_id: str, return_url: str) -> str:
        """Create Customer Portal session, return session URL."""
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url

    @staticmethod
    def cancel_subscription(
        subscription_id: str, at_period_end: bool = True
    ) -> None:
        """Cancel subscription (default: at period end)."""
        if at_period_end:
            stripe.Subscription.modify(
                subscription_id, cancel_at_period_end=True
            )
        else:
            stripe.Subscription.cancel(subscription_id)

    @staticmethod
    def construct_webhook_event(
        payload: bytes, sig_header: str
    ) -> stripe.Event:
        """Verify and construct webhook event from signed payload."""
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )

    @staticmethod
    def create_invoice_item(
        customer_id: str,
        amount_cents: int,
        description: str,
        product_id: str,
        metadata: dict | None = None,
    ) -> str:
        """Add a pending invoice item to a customer.

        Uses price_data with the product for proper revenue categorization.
        Stripe auto-includes pending items on the next subscription invoice.
        Returns the invoice item ID.
        """
        item = stripe.InvoiceItem.create(
            customer=customer_id,
            price_data={
                "currency": "usd",
                "product": product_id,
                "unit_amount": amount_cents,
            },
            quantity=1,
            description=description,
            metadata=metadata or {},
        )
        logger.info(
            f"Created invoice item {item.id} for {customer_id}: "
            f"{description} (${amount_cents / 100:.2f})"
        )
        return item.id

    @staticmethod
    def get_upcoming_invoice(customer_id: str) -> stripe.Invoice | None:
        """Retrieve the upcoming invoice for preview. None if no upcoming invoice."""
        try:
            return stripe.Invoice.upcoming(customer=customer_id)
        except stripe.InvalidRequestError:
            return None

    @staticmethod
    def list_pending_invoice_items(customer_id: str) -> list:
        """List pending (not yet invoiced) items for a customer."""
        items = stripe.InvoiceItem.list(customer=customer_id, pending=True)
        return items.data
