"""Authentication utilities for JWT token handling using JWKS."""

from typing import Optional
from uuid import UUID
from jose import jwt, JWTError
from fastapi import Header, HTTPException, status
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.auth_cache import auth_cache
from app.models.database.user import User


async def get_current_user_id(
    authorization: Optional[str] = Header(None)
) -> Optional[UUID]:
    """
    Extract user_id from Supabase JWT token using JWKS.

    Process:
    1. Extract Bearer token from Authorization header
    2. Extract kid (key ID) from JWT header (unverified)
    3. Fetch public key from JWKS cache (auto-refreshes if needed)
    4. Verify JWT signature using fetched key
    5. Extract auth_uid from 'sub' claim
    6. Look up User by auth_uid (indexed query)
    7. Return user.id (internal UUID)

    JWKS Benefits:
    - Automatic key rotation (Supabase updates JWKS, we auto-fetch)
    - Zero downtime during rotation (grace period with old + new keys)
    - No secrets in config (JWKS endpoint is public)
    - Industry standard (OAuth 2.0 / OIDC)

    CRITICAL: Returns user.id (NOT auth_uid!)
    - auth_uid: Supabase auth.users.id (external identifier)
    - user.id: Our users table PK (internal, used in animas.user_id)

    Performance:
    - First request: ~10ms (fetch JWKS) + 1ms (verify) = ~11ms
    - Subsequent: ~1ms (cached key)
    - Cache refresh: Automatic (1 hour TTL)

    Security:
    - Verifies cryptographic signature (prevents token forgery)
    - Checks expiration (rejects stale tokens)
    - Fetches keys from trusted source (Supabase)
    - Automatic response to key compromise (Supabase rotates → we refresh)

    Args:
        authorization: Authorization header with Bearer token

    Returns:
        User UUID if authenticated, None otherwise
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")

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
            print("❌ No 'sub' claim in JWT payload")
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
                print(f"❌ User not found for auth_uid: {auth_uid[:8]}...")
                return None

            # Phase 3: Return user.id
            # Full RLS context (app.current_user) set by get_db_with_rls dependency
            return user.id  # CRITICAL: Return user.id, not auth_uid!
        finally:
            db.close()

    except jwt.ExpiredSignatureError:
        # Token expired - frontend will refresh
        print("❌ JWT expired")
        return None
    except JWTError as e:
        # Invalid signature, malformed token, etc.
        print(f"❌ JWT error: {e}")
        return None
    except Exception as e:
        # JWKS fetch error, database error, unexpected issue
        # Log this in production!
        print(f"❌ Unexpected error in get_current_user_id: {e}")
        return None


async def require_current_user_id(
    authorization: Optional[str] = Header(None)
) -> UUID:
    """
    Extract and require user_id from JWT token.

    Raises HTTPException if no valid token provided.
    Use this when endpoint requires authentication.

    Args:
        authorization: Authorization header with Bearer token

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
