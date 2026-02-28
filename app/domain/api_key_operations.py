"""Domain operations for API Keys - SDK authentication.

API keys enable programmatic access alongside JWT auth.
Key format: sk_live_<32-char-hex>
"""

import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from sqlalchemy import select
from sqlmodel import Session
from app.domain.exceptions import DomainValidationError
from app.models.database.api_key import APIKey, APIKeyCreate


class APIKeyOperations:
    """
    API Key business logic. Static methods, sync session-based, no commits.
    """

    # Key format constants
    KEY_PREFIX = "sk_live_"
    KEY_RANDOM_BYTES = 16  # 32 hex chars

    @staticmethod
    def generate_key() -> tuple[str, str, str]:
        """
        Generate a new API key with hash and prefix.

        Returns:
            (full_key, key_hash, key_prefix)
            - full_key: sk_live_<32-char-hex> - return to user once
            - key_hash: bcrypt hash for storage
            - key_prefix: first 12 chars for display (sk_live_xxxx)
        """
        # Generate random hex string
        random_part = secrets.token_hex(APIKeyOperations.KEY_RANDOM_BYTES)
        full_key = f"{APIKeyOperations.KEY_PREFIX}{random_part}"

        # Hash with bcrypt (encode to bytes, decode result back to string)
        key_hash = bcrypt.hashpw(
            full_key.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        # Prefix for display (sk_live_ + first 4 of random = 12 chars)
        key_prefix = full_key[:12]

        return full_key, key_hash, key_prefix

    @staticmethod
    def create(
        session: Session,
        user_id: UUID,
        data: APIKeyCreate
    ) -> tuple[APIKey, str]:
        """
        Create a new API key for a user.

        Returns:
            (APIKey, full_key) - full_key is only returned once at creation

        Note: Caller must store/display full_key immediately; it cannot be retrieved later.
        """
        full_key, key_hash, key_prefix = APIKeyOperations.generate_key()

        api_key = APIKey(
            user_id=user_id,
            name=data.name,
            description=data.description,
            key_hash=key_hash,
            key_prefix=key_prefix,
        )

        session.add(api_key)
        session.flush()
        session.refresh(api_key)

        return api_key, full_key

    @staticmethod
    def validate_key(
        session: Session,
        full_key: str
    ) -> Optional[APIKey]:
        """
        Validate an API key and return the associated key record.

        Checks:
        1. Key format matches sk_live_*
        2. Key prefix exists in database
        3. Key is active (not revoked)
        4. Key is not expired
        5. bcrypt hash matches

        On success, updates last_used_at and request_count.

        Returns:
            APIKey if valid, None if invalid/expired/revoked
        """
        # Check format
        if not full_key.startswith(APIKeyOperations.KEY_PREFIX):
            return None

        # Extract prefix for lookup (first 12 chars)
        key_prefix = full_key[:12]

        # Find key by prefix (may have multiple with same prefix, rare but possible)
        query = select(APIKey).where(
            APIKey.key_prefix == key_prefix,
            APIKey.is_active.is_(True)
        )
        result = session.execute(query)
        candidates = result.scalars().all()

        if not candidates:
            return None

        now = datetime.now(timezone.utc)

        # Check each candidate (usually just one)
        for api_key in candidates:
            # Check expiration
            if api_key.expires_at and api_key.expires_at < now:
                continue

            # Verify bcrypt hash
            if bcrypt.checkpw(full_key.encode('utf-8'), api_key.key_hash.encode('utf-8')):
                # Update usage stats
                api_key.last_used_at = now
                api_key.request_count += 1
                session.add(api_key)
                session.flush()
                return api_key

        return None

    @staticmethod
    def get_by_user(
        session: Session,
        user_id: UUID,
        include_inactive: bool = False
    ) -> list[APIKey]:
        """
        Get all API keys for a user.

        Args:
            user_id: Owner user ID
            include_inactive: If True, include revoked keys

        Returns:
            List of APIKey (without hashes exposed via DTO)
        """
        query = select(APIKey).where(APIKey.user_id == user_id)

        if not include_inactive:
            query = query.where(APIKey.is_active.is_(True))

        query = query.order_by(APIKey.created_at.desc())

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_by_id(
        session: Session,
        key_id: UUID,
        user_id: UUID
    ) -> Optional[APIKey]:
        """
        Get a specific API key by ID (with ownership check).

        Returns:
            APIKey if found and owned by user, None otherwise
        """
        api_key = session.get(APIKey, key_id)

        if api_key is None:
            return None

        # Ownership check (defense in depth - RLS also enforces)
        if api_key.user_id != user_id:
            return None

        return api_key

    @staticmethod
    def revoke(
        session: Session,
        key_id: UUID,
        user_id: UUID
    ) -> Optional[APIKey]:
        """
        Revoke an API key (soft disable).

        Returns:
            Revoked APIKey, or None if not found/not owned

        Raises:
            DomainValidationError if key already revoked
        """
        api_key = APIKeyOperations.get_by_id(session, key_id, user_id)

        if api_key is None:
            return None

        if not api_key.is_active:
            raise DomainValidationError("API key is already revoked")

        api_key.is_active = False
        session.add(api_key)
        session.flush()

        return api_key

    @staticmethod
    def delete(
        session: Session,
        key_id: UUID,
        user_id: UUID
    ) -> bool:
        """
        Hard delete an API key.

        Returns:
            True if deleted, False if not found/not owned
        """
        api_key = APIKeyOperations.get_by_id(session, key_id, user_id)

        if api_key is None:
            return False

        session.delete(api_key)
        session.flush()

        return True
