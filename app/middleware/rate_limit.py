"""Rate limiting middleware for Elephantasm API.

Uses slowapi for MVP (single Fly.io instance).
Rate limits based on organization's plan tier.

Future: Migrate to Redis-backed solution for multi-replica deployment.
"""

import logging
from typing import Optional, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.database import SessionLocal
from app.config.plans import get_plan

logger = logging.getLogger(__name__)

# Cache for org plan lookups (simple in-memory, clears on restart)
# Key: org_id, Value: (rate_limit, expires_at)
_plan_cache: dict[str, tuple[int, float]] = {}
CACHE_TTL_SECONDS = 60  # Refresh plan lookup every minute


def _get_org_id_from_request(request: Request) -> Optional[str]:
    """
    Extract organization ID from request.

    Tries to get org_id from:
    1. Request state (set by auth middleware)
    2. JWT token parsing (fallback)

    Returns:
        org_id string or None if not authenticated
    """
    # Check if org_id was set by previous middleware/dependency
    if hasattr(request.state, "org_id"):
        return str(request.state.org_id)

    # Try to extract from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.replace("Bearer ", "")

    # Skip API keys - they don't have org_id embedded
    if token.startswith("sk_live_"):
        # For API keys, we'd need to look up the user
        # For now, use IP-based rate limiting for API keys
        return None

    # For JWTs, we'd need to decode to get user_id, then look up org
    # This is expensive, so we'll use a simplified approach:
    # Rate limit by IP for now, with plan-based limits checked in route handlers

    return None


def get_rate_limit_key(request: Request) -> str:
    """
    Generate rate limit key based on request.

    Key strategy:
    - Authenticated (org_id available): "org:{org_id}"
    - Unauthenticated: IP address

    Args:
        request: FastAPI request

    Returns:
        Rate limit key string
    """
    org_id = _get_org_id_from_request(request)

    if org_id:
        return f"org:{org_id}"

    # Fall back to IP address
    return get_remote_address(request)


def _get_plan_rate_limit(org_id: str) -> int:
    """
    Get rate limit for organization based on plan tier.

    Uses simple in-memory cache to avoid DB lookups on every request.

    Args:
        org_id: Organization UUID string

    Returns:
        Rate limit per second
    """
    import time

    # Check cache
    if org_id in _plan_cache:
        rate_limit, expires_at = _plan_cache[org_id]
        if time.time() < expires_at:
            return rate_limit

    # Cache miss or expired - look up from DB
    try:
        from app.domain.organization_operations import OrganizationOperations
        from app.domain.subscription_operations import SubscriptionOperations
        from uuid import UUID

        db = SessionLocal()
        try:
            subscription = SubscriptionOperations.get_by_org(db, UUID(org_id))
            plan = get_plan(subscription.plan_tier if subscription else "free")
            rate_limit = plan.api_rate_limit_per_second

            # Handle unlimited (-1)
            if rate_limit == -1:
                rate_limit = 1000  # Cap at 1000/sec for unlimited plans

            # Cache the result
            _plan_cache[org_id] = (rate_limit, time.time() + CACHE_TTL_SECONDS)

            return rate_limit
        finally:
            db.close()

    except Exception as e:
        logger.warning(f"Failed to get plan rate limit for org {org_id}: {e}")
        return 5  # Default to free tier limit on error


def dynamic_rate_limit(key: str) -> str:
    """
    Return dynamic rate limit string based on key.

    For org keys: Look up plan-based limit
    For IP keys: Use default (unauthenticated) limit

    Args:
        key: Rate limit key (org:{id} or IP address)

    Returns:
        Rate limit string (e.g., "100/second")
    """
    if key.startswith("org:"):
        org_id = key.split(":", 1)[1]
        rate_limit = _get_plan_rate_limit(org_id)
        return f"{rate_limit}/second"

    # Unauthenticated - use minimal rate limit
    return "5/second"


# Create limiter with custom key function
# Note: slowapi's default_limits applies to all routes
# We use per-route limits for more control
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["100/second"],  # High default, routes override
    enabled=True,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns JSON response with retry information.
    """
    # Extract retry-after from exception
    retry_after = "1"  # Default 1 second
    if hasattr(exc, "detail") and exc.detail:
        retry_after = str(exc.detail)

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down.",
            "retry_after_seconds": retry_after,
            "upgrade_url": "/settings/billing"
        },
        headers={"Retry-After": retry_after}
    )


def get_rate_limiter() -> Limiter:
    """Get the configured rate limiter instance."""
    return limiter


def clear_rate_limit_cache():
    """Clear the plan rate limit cache. Used for testing."""
    _plan_cache.clear()
