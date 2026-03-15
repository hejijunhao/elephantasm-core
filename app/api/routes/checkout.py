"""Checkout routes — Stripe Checkout sessions and Customer Portal."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_subscription_context, SubscriptionContext
from app.core.config import settings
from app.core.rls_dependencies import get_db_with_rls
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.user_operations import UserOperations
from app.services.stripe_service import StripeService

router = APIRouter(prefix="/checkout", tags=["checkout"])

ALLOWED_REDIRECT_DOMAINS = {"elephantasm.com", "www.elephantasm.com", "localhost"}


def _validate_redirect_url(url: str) -> None:
    """Reject redirect URLs pointing to external domains."""
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname not in ALLOWED_REDIRECT_DOMAINS:
        raise HTTPException(400, "Redirect URL must point to an allowed domain")


class CheckoutRequest(BaseModel):
    plan_tier: str
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalRequest(BaseModel):
    return_url: str


class PortalResponse(BaseModel):
    portal_url: str


@router.post("/create-session", response_model=CheckoutResponse)
async def create_checkout_session(
    data: CheckoutRequest,
    ctx: SubscriptionContext = Depends(get_subscription_context),
    db: Session = Depends(get_db_with_rls),
) -> CheckoutResponse:
    """Create Stripe Checkout session for plan upgrade."""
    _validate_redirect_url(data.success_url)
    _validate_redirect_url(data.cancel_url)

    if data.plan_tier not in ("pro", "team"):
        raise HTTPException(400, "Only Pro and Team plans are available for checkout")

    # Prevent checkout if already on target plan
    if ctx.subscription and ctx.subscription.plan_tier == data.plan_tier:
        raise HTTPException(400, f"Already on {data.plan_tier} plan")

    # Get or create Stripe customer
    if ctx.subscription and ctx.subscription.stripe_customer_id:
        customer_id = ctx.subscription.stripe_customer_id
    else:
        user = UserOperations.get_by_id(db, ctx.user_id)
        name = ""
        email = ""
        if user:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or ""
            email = user.email or ""

        customer_id = StripeService.create_customer(
            email=email,
            name=name,
            org_id=str(ctx.org_id),
        )
        SubscriptionOperations.set_stripe_ids(db, ctx.org_id, stripe_customer_id=customer_id)

    # Map tier to Stripe price ID
    try:
        price_id = settings.get_stripe_price(data.plan_tier)
    except ValueError:
        raise HTTPException(400, f"Stripe pricing not configured for {data.plan_tier} tier")

    checkout_url = StripeService.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=data.success_url,
        cancel_url=data.cancel_url,
        org_id=str(ctx.org_id),
    )

    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/create-portal-session", response_model=PortalResponse)
async def create_portal_session(
    data: PortalRequest,
    ctx: SubscriptionContext = Depends(get_subscription_context),
) -> PortalResponse:
    """Create Stripe Customer Portal session for subscription management."""
    _validate_redirect_url(data.return_url)

    if not ctx.subscription or not ctx.subscription.stripe_customer_id:
        raise HTTPException(400, "No Stripe customer found. Please upgrade first.")

    portal_url = StripeService.create_portal_session(
        customer_id=ctx.subscription.stripe_customer_id,
        return_url=data.return_url,
    )

    return PortalResponse(portal_url=portal_url)
