"""Authentication cache for JWT public key management.

Fetches and caches Supabase's public keys from the .well-known/jwks.json endpoint.
Handles automatic key rotation without manual configuration updates.
"""

from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import httpx
from jose import jwk

from app.core.config import settings


class AuthCache:
    """
    Cache for JWT public keys (JWKS - JSON Web Key Set).

    Fetches public keys from Supabase's .well-known/jwks.json endpoint and caches
    them in memory. Automatically refreshes when keys expire or are missing.

    Key rotation handling:
    - Supabase publishes multiple keys during rotation (old + new)
    - We cache all available keys by their kid (key ID)
    - When verification fails, we refresh and retry once
    - Zero downtime during key rotation

    Performance:
    - First request: ~10ms (fetch JWKS)
    - Subsequent requests: <1ms (cached)
    - Cache TTL: 1 hour (configurable)
    """

    def __init__(self, ttl_hours: int = 1):
        """
        Initialize authentication cache.

        Args:
            ttl_hours: Cache time-to-live in hours (default: 1)
        """
        self.keys: Dict[str, str] = {}  # kid -> PEM public key
        self.last_refresh: Optional[datetime] = None
        self.ttl = timedelta(hours=ttl_hours)
        self._client: Optional[httpx.AsyncClient] = None

        # JWT payload cache: token -> (payload, expiry)
        # Saves ~1ms per request by skipping re-verification
        self.payload_cache: Dict[str, tuple[dict, datetime]] = {}
        self.payload_ttl = timedelta(minutes=5)  # Short TTL for security

    def _needs_refresh(self) -> bool:
        """Check if cache needs refresh (expired or empty)."""
        if not self.last_refresh or not self.keys:
            return True
        return datetime.now(timezone.utc) - self.last_refresh > self.ttl

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client (reuse connections)."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def _refresh_keys(self) -> None:
        """
        Fetch JWKS from Supabase and update cache.

        Fetches from: https://<project>.supabase.co/auth/v1/.well-known/jwks.json

        Response format:
        {
          "keys": [
            {
              "kid": "key-abc-123",
              "kty": "EC",
              "crv": "P-256",
              "x": "...",
              "y": "...",
              "use": "sig",
              "alg": "ES256"
            }
          ]
        }

        Raises:
            httpx.HTTPError: If JWKS endpoint unreachable
            ValueError: If JWKS format invalid
        """
        if not settings.SUPABASE_URL:
            raise ValueError("SUPABASE_URL not configured")

        # Construct JWKS endpoint URL
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"

        # Fetch JWKS
        client = await self._get_client()
        response = await client.get(jwks_url)
        response.raise_for_status()
        jwks_data = response.json()

        # Parse and cache keys
        keys_data = jwks_data.get("keys", [])
        if not keys_data:
            raise ValueError("JWKS response contains no keys")

        new_keys = {}
        for key_data in keys_data:
            kid = key_data.get("kid")
            if not kid:
                continue  # Skip keys without kid

            # Convert JWK to PEM format for JWT verification
            # python-jose's jwk.construct handles the conversion
            key_obj = jwk.construct(key_data)
            public_key_pem = key_obj.to_pem().decode('utf-8')
            new_keys[kid] = public_key_pem

        # Atomic update
        self.keys = new_keys
        self.last_refresh = datetime.now(timezone.utc)

    async def get_key(self, kid: str, retry: bool = True) -> Optional[str]:
        """
        Get public key by kid (key ID).

        If key not in cache or cache expired, refreshes from JWKS endpoint.

        Args:
            kid: Key ID from JWT header
            retry: If True, refresh and retry once on cache miss (default: True)

        Returns:
            Public key in PEM format, or None if kid not found

        Example:
            cache = AuthCache()
            key = await cache.get_key("key-abc-123")
            if key:
                jwt.decode(token, key, algorithms=["ES256"])
        """
        # Refresh if cache expired or empty
        if self._needs_refresh():
            await self._refresh_keys()

        # Return cached key if available
        if kid in self.keys:
            return self.keys[kid]

        # Cache miss - refresh and retry once
        if retry:
            await self._refresh_keys()
            return self.keys.get(kid)  # No retry on second miss

        return None

    def get_payload(self, token: str) -> Optional[dict]:
        """
        Get cached JWT payload if available and not expired.

        Args:
            token: JWT token string

        Returns:
            Cached payload dict, or None if not cached or expired
        """
        if token not in self.payload_cache:
            return None

        payload, expiry = self.payload_cache[token]

        # Check if expired
        if datetime.now(timezone.utc) >= expiry:
            # Clean up expired entry
            del self.payload_cache[token]
            return None

        return payload

    def set_payload(self, token: str, payload: dict) -> None:
        """
        Cache a verified JWT payload.

        Args:
            token: JWT token string
            payload: Verified payload dict
        """
        expiry = datetime.now(timezone.utc) + self.payload_ttl
        self.payload_cache[token] = (payload, expiry)

        # Periodic cleanup: remove expired entries if cache growing
        if len(self.payload_cache) > 100:
            now = datetime.now(timezone.utc)
            self.payload_cache = {
                t: (p, e) for t, (p, e) in self.payload_cache.items()
                if e > now
            }

    async def close(self) -> None:
        """Close HTTP client (cleanup)."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Global authentication cache instance (singleton pattern)
# Shared across all requests for efficient caching
auth_cache = AuthCache()
