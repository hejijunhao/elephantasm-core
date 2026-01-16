"""API Key model - enables programmatic SDK access alongside JWT auth."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.user import User


class APIKeyBase(SQLModel):
    """Shared fields for APIKey model."""
    name: str = Field(max_length=255, description="User-friendly key name (e.g., 'Production SDK')")
    description: str | None = Field(default=None, max_length=1000, nullable=True, description="Optional key description")


class APIKey(APIKeyBase, TimestampMixin, table=True):
    """API Key entity - enables programmatic access via SDK.

    Key format: sk_live_<32-char-hex>
    - sk_live_ prefix identifies Elephantasm keys
    - Only bcrypt hash stored; full key returned once at creation
    """
    __tablename__ = "api_keys"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    user_id: UUID = Field(foreign_key="users.id", index=True, description="Owner user ID")
    key_hash: str = Field(max_length=255, description="bcrypt hash of full key (never store plaintext)")
    key_prefix: str = Field(max_length=16, description="First 12 chars for identification (e.g., 'sk_live_abc1')")
    last_used_at: datetime | None = Field(default=None, nullable=True, description="Last successful authentication")
    request_count: int = Field(default=0, ge=0, description="Total successful authentications")
    is_active: bool = Field(default=True, description="False = revoked")
    expires_at: datetime | None = Field(default=None, nullable=True, description="Optional expiration (null = never)")

    # Relationships
    user: "User" = Relationship(back_populates="api_keys")


class APIKeyCreate(SQLModel):
    """Data required to create an API Key."""
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class APIKeyRead(APIKeyBase):
    """Data returned when reading an API Key (no hash, no full key)."""
    id: UUID
    key_prefix: str
    last_used_at: datetime | None
    request_count: int
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APIKeyCreateResponse(APIKeyRead):
    """Response when creating an API Key - includes full key (shown once only)."""
    full_key: str = Field(description="Full API key - store securely, shown only once")
