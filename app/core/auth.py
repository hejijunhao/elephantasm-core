"""Authentication utilities for JWT and API key handling.

Dual auth support:
- JWT tokens (Bearer <jwt>) → JWKS validation → user.id
- API keys (Bearer sk_live_*) → bcrypt validation → user.id

Both paths return the same user.id for RLS context.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from jose import jwt, JWTError
from fastapi import Header, HTTPException, status
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.auth_cache import auth_cache
from app.models.database.user import User

logger = logging.getLogger(__name__)

# API key prefix for detection
API_KEY_PREFIX = "sk_live_"


def _validate_api_key(api_key: str) -> Optional[UUID]:
    """
    Validate an API key via SECURITY DEFINER bypass (RLS bootstrap).

    Uses app.validate_api_key_lookup() to bypass RLS on api_keys table,
    then bcrypt-verifies the key. On success, records usage via
    app.record_api_key_usage().

    This solves the chicken-and-egg problem: RLS on api_keys requires
    user_id, but user_id is only known after validating the key.

    Args:
        api_key: Full API key (sk_live_...)

    Returns:
        user_id if valid, None otherwise
    """
    if not api_key.startswith(API_KEY_PREFIX):
        return None

    key_prefix = api_key[:12]
    db = SessionLocal()
    try:
        # SECURITY DEFINER function bypasses RLS to find candidates by prefix
        result = db.execute(
            text("SELECT id, user_id, key_hash, is_active, expires_at "
                 "FROM app.validate_api_key_lookup(:prefix)"),
            {"prefix": key_prefix}
        )
        candidates = result.fetchall()

        if not candidates:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for row in candidates:
            # Check expiration
            if row.expires_at and row.expires_at < now:
                continue

            # Verify bcrypt hash
            if bcrypt.checkpw(api_key.encode('utf-8'), row.key_hash.encode('utf-8')):
                # Record usage via SECURITY DEFINER (also bypasses RLS)
                db.execute(
                    text("SELECT app.record_api_key_usage(:key_id)"),
                    {"key_id": row.id}
                )
                db.commit()
                return row.user_id

        return None
    except Exception as e:
        logger.error("API key validation error: %s", e)
        db.rollback()
        return None
    finally:
        db.close()


async def get_current_user_id(
    authorization: Optional[str] = Header(None)
) -> Optional[UUID]:
    """
    Extract user_id from JWT token or API key.

    Dual Auth Flow:
    1. Extract Bearer token from Authorization header
    2. If token starts with 'sk_live_' → API key validation
    3. Otherwise → JWT/JWKS validation
    4. Both paths return user.id for RLS context

    API Key Flow:
    - Detect sk_live_ prefix
    - Validate via APIKeyOperations.validate_key()
    - Update usage stats (last_used_at, request_count)
    - Return user_id from API key record

    JWT Flow:
    - Extract kid from JWT header
    - Fetch public key from JWKS cache
    - Verify signature, audience, issuer, expiration
    - Look up User by auth_uid
    - Return user.id

    CRITICAL: Returns user.id (NOT auth_uid!)
    - auth_uid: Supabase auth.users.id (external identifier)
    - user.id: Our users table PK (internal, used in animas.user_id)

    Args:
        authorization: Authorization header with Bearer token or API key

    Returns:
        User UUID if authenticated, None otherwise
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")

    # Check if this is an API key (sk_live_...) vs JWT
    if token.startswith(API_KEY_PREFIX):
        return _validate_api_key(token)

    try:
        # If Supabase URL not configured, skip validation (dev mode)
        if not settings.SUPABASE_URL:
            return None

        # Check payload cache first (saves ~1ms per request)
        cached_payload = auth_cache.get_payload(token)
        if cached_payload:
            payload = cached_payload
        else:
            # Cache miss - verify JWT
            # Extract kid (key ID) from JWT header without verification
            # This tells us which key Supabase used to sign this token
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                # Token missing kid - invalid format
                return None

            # Fetch public key from auth cache
            # Cache automatically refreshes if key missing or expired
            public_key = await auth_cache.get_key(kid)

            if not public_key:
                # Key not found even after refresh - invalid kid
                return None

            # Verify JWT signature using fetched public key
            # ES256 algorithm with ECC P256 (Supabase standard)
            # Strict validation: issuer, audience, expiration, required claims
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],  # ECC P256 only
                audience="authenticated",  # Supabase standard audience claim
                issuer=f"{settings.SUPABASE_URL}/auth/v1",  # Prevent token reuse from other projects
                options={
                    "verify_exp": True,   # Reject expired tokens
                    "verify_nbf": True,   # Verify not-before claim
                    "verify_iat": True,   # Verify issued-at claim
                    "verify_aud": True,   # Verify audience explicitly
                    "require_exp": True,  # Require expiration claim
                    "require_iat": True,  # Require issued-at claim
                    "require_sub": True   # Require subject claim
                }
            )

            # Cache the verified payload for subsequent requests
            auth_cache.set_payload(token, payload)

        # Extract auth_uid from 'sub' claim (standard JWT claim)
        auth_uid = payload.get("sub")
        if not auth_uid:
            logger.warning("No 'sub' claim in JWT payload")
            return None

        # Two-phase bootstrap to resolve chicken-egg RLS problem
        # Phase 1: Set minimal RLS context (auth_uid only)
        # Phase 2: Query users table (bootstrap policy allows this)
        # Phase 3: Return user.id (full RLS context set by get_db_with_rls)

        db = SessionLocal()
        try:
            # Phase 1: Set auth_uid for bootstrap policy
            # This enables users_bootstrap_auth policy (auth_uid = app.effective_uid())
            db.execute(
                text("SELECT set_config('app.auth_uid', :auth_uid, true)"),
                {"auth_uid": auth_uid}
            )

            # Phase 2: Query users table
            # Bootstrap policy allows SELECT with just auth_uid set
            result = db.execute(
                select(User).where(User.auth_uid == auth_uid)
            )
            user = result.scalar_one_or_none()

            if not user:
                # User authenticated in Supabase but not in our DB
                # This shouldn't happen (trigger creates users automatically)
                logger.warning("User not found for auth_uid: %s...", auth_uid[:8])
                return None

            # Phase 3: Return user.id
            # Full RLS context (app.current_user) set by get_db_with_rls dependency
            return user.id  # CRITICAL: Return user.id, not auth_uid!
        finally:
            db.close()

    except jwt.ExpiredSignatureError:
        # Token expired - frontend will refresh
        logger.warning("JWT expired")
        return None
    except JWTError as e:
        # Invalid signature, malformed token, etc.
        logger.warning("JWT error: %s", e)
        return None
    except Exception as e:
        # JWKS fetch error, database error, unexpected issue
        # Log this in production!
        logger.error("Unexpected error in get_current_user_id: %s", e)
        return None


async def require_current_user_id(
    authorization: Optional[str] = Header(None)
) -> UUID:
    """
    Extract and require user_id from JWT token or API key.

    Raises HTTPException if no valid token/key provided.
    Use this when endpoint requires authentication.

    Accepts:
    - Bearer <jwt> → JWT/JWKS validation
    - Bearer sk_live_* → API key validation

    Args:
        authorization: Authorization header with Bearer token or API key

    Returns:
        User UUID

    Raises:
        HTTPException: 401 if not authenticated
    """
    user_id = await get_current_user_id(authorization)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id
