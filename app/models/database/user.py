"""User model - represents a human user in Elephantasm."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel

from app.models.database.mixins.timestamp import TimestampMixin


class UserBase(SQLModel):
    """Shared fields for User model."""
    auth_uid: UUID = Field(unique=True, index=True, description="Supabase auth.users.id reference (from JWT 'sub' claim)")
    email: str | None = Field(default=None, max_length=255, nullable=True, description="User's email address")
    first_name: str | None = Field(default=None, max_length=255, nullable=True, description="User's first name")
    last_name: str | None = Field(default=None, max_length=255, nullable=True, description="User's last name")
    phone: str | None = Field(default=None, max_length=50, nullable=True, description="User's phone number")
    username: str | None = Field(default=None, max_length=255, nullable=True, description="User's username")


class User(UserBase, TimestampMixin, table=True):
    """User entity - represents a human user."""
    __tablename__ = "users"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False)

    # Relationships
    # spirits: list["Spirit"] = Relationship(back_populates="user") # TODO: populate if needed


class UserCreate(UserBase):
    """Data required to create a User."""
    pass


class UserRead(UserBase):
    """Data returned when reading a User."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class UserUpdate(SQLModel):
    """Fields that can be updated."""
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    username: str | None = None
    is_deleted: bool | None = None
