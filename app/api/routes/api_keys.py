"""API Keys endpoints for SDK authentication management.

Pattern: Async routes + Sync domain operations + RLS filtering.

Endpoints:
- POST /api-keys — create new key (returns full key once)
- GET /api-keys — list user's keys (prefix only)
- POST /api-keys/{id}/revoke — soft disable key
- DELETE /api-keys/{id} — hard delete key
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.core.auth import require_current_user_id
from app.domain.api_key_operations import APIKeyOperations
from app.models.database.api_key import (
    APIKeyCreate,
    APIKeyRead,
    APIKeyCreateResponse,
)


router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post(
    "",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new API key"
)
async def create_api_key(
    data: APIKeyCreate,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> APIKeyCreateResponse:
    """
    Create a new API key for SDK access.

    **Important:** The full key is only returned once at creation.
    Store it securely — it cannot be retrieved later.

    Key format: `sk_live_<32-char-hex>`
    """
    api_key, full_key = APIKeyOperations.create(db, user_id, data)

    # Build response with full_key (only time it's exposed)
    response = APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        description=api_key.description,
        key_prefix=api_key.key_prefix,
        last_used_at=api_key.last_used_at,
        request_count=api_key.request_count,
        is_active=api_key.is_active,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        full_key=full_key,
    )
    return response


@router.get(
    "",
    response_model=list[APIKeyRead],
    summary="List API keys"
)
async def list_api_keys(
    include_inactive: bool = False,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> list[APIKeyRead]:
    """
    List all API keys for the authenticated user.

    By default only shows active keys. Set `include_inactive=true`
    to include revoked keys.

    Note: Full keys are never returned — only the prefix for identification.
    """
    keys = APIKeyOperations.get_by_user(db, user_id, include_inactive)
    return [APIKeyRead.model_validate(k) for k in keys]


@router.post(
    "/{key_id}/revoke",
    response_model=APIKeyRead,
    summary="Revoke API key"
)
async def revoke_api_key(
    key_id: UUID,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> APIKeyRead:
    """
    Revoke an API key (soft disable).

    The key will no longer authenticate requests.
    This action can be undone by creating a new key.
    """
    api_key = APIKeyOperations.revoke(db, key_id, user_id)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    return APIKeyRead.model_validate(api_key)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete API key"
)
async def delete_api_key(
    key_id: UUID,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> None:
    """
    Permanently delete an API key.

    This action cannot be undone.
    """
    deleted = APIKeyOperations.delete(db, key_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
