"""Users API endpoints for profile management.

Pattern: Async routes + Sync domain operations + RLS filtering.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.core.auth import require_current_user_id
from app.domain.user_operations import UserOperations
from app.models.database.user import UserRead, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user profile"
)
async def get_current_user_profile(
    user_id=Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> UserRead:
    """
    Get the authenticated user's profile from public.users table.
    """
    user = UserOperations.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    return UserRead.model_validate(user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update current user profile"
)
async def update_current_user_profile(
    data: UserUpdate,
    user_id=Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> UserRead:
    """
    Update the authenticated user's profile.

    Can update: first_name, last_name, username, phone.
    Email changes require Supabase auth flow.
    """
    try:
        user = UserOperations.update(db, user_id, data)
        return UserRead.model_validate(user)
    except HTTPException:
        raise
