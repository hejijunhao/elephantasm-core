"""Rate limiting middleware (OSS version — flat-rate limits, no plan tiers).

Uses slowapi with a fixed rate limit for all requests.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

# Fixed rate limit for OSS (no plan-based tiers)
DEFAULT_RATE_LIMIT = "100/second"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_RATE_LIMIT],
    enabled=True,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down.",
        },
        headers={"Retry-After": "1"},
    )


def get_rate_limiter() -> Limiter:
    """Get the configured rate limiter instance."""
    return limiter


def clear_rate_limit_cache():
    """No-op in OSS version (no plan cache)."""
    pass
