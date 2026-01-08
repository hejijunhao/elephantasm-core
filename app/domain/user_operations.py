"""Domain operations for Users - profile management.

User data comes from public.users table (not Supabase auth schema).
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlmodel import Session
from fastapi import HTTPException

from app.models.database.user import User, UserUpdate


class UserOperations:
    """
    User business logic. Static methods, sync session-based, no commits.
    """

    @staticmethod
    def get_by_id(
        session: Session,
        user_id: UUID,
        include_deleted: bool = False
    ) -> Optional[User]:
        """Get user by ID. Returns None if not found or soft-deleted."""
        user = session.get(User, user_id)

        if user is None:
            return None

        if not include_deleted and user.is_deleted:
            return None

        return user

    @staticmethod
    def get_by_auth_uid(
        session: Session,
        auth_uid: UUID,
        include_deleted: bool = False
    ) -> Optional[User]:
        """Get user by Supabase auth UID. Used for profile lookups."""
        query = select(User).where(User.auth_uid == auth_uid)

        if not include_deleted:
            query = query.where(User.is_deleted.is_(False))

        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def update(
        session: Session,
        user_id: UUID,
        data: UserUpdate
    ) -> User:
        """
        Update user profile (partial). Raises HTTPException 404 if not found.
        """
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} not found"
            )

        # Update only provided fields
        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(user, key, value)

        session.add(user)
        session.flush()
        return user
