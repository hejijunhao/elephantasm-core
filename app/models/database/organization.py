"""Organization model - multi-tenant billing entity in Elephantasm."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.user import User
    from app.models.database.subscription import Subscription


class MemberRole(str, Enum):
    """Organization member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationBase(SQLModel):
    """Shared fields for Organization model."""
    name: str = Field(max_length=255, index=True, description="Organization display name")
    slug: str = Field(max_length=100, unique=True, index=True, description="URL-friendly identifier")
    meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))


class Organization(OrganizationBase, TimestampMixin, table=True):
    """Organization entity - billing and team grouping."""
    __tablename__ = "organizations"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    is_deleted: bool = Field(default=False)

    # Relationships
    members: list["OrganizationMember"] = Relationship(back_populates="organization")
    subscription: Optional["Subscription"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"uselist": False}
    )


class OrganizationCreate(SQLModel):
    """Data required to create an Organization."""
    name: str = Field(max_length=255, description="Organization display name")
    slug: str | None = Field(default=None, max_length=100, description="URL-friendly identifier (auto-generated if not provided)")
    meta: dict[str, Any] | None = None


class OrganizationRead(OrganizationBase):
    """Data returned when reading an Organization."""
    id: UUID
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class OrganizationUpdate(SQLModel):
    """Fields that can be updated."""
    name: str | None = None
    meta: dict[str, Any] | None = None
    is_deleted: bool | None = None


# --- Organization Member ---

class OrganizationMemberBase(SQLModel):
    """Shared fields for OrganizationMember model."""
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member", max_length=50, description="Role: owner, admin, member")


class OrganizationMember(OrganizationMemberBase, TimestampMixin, table=True):
    """Organization membership - links users to organizations."""
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_member_user", "user_id"),
    )

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})

    # Relationships
    organization: Organization = Relationship(back_populates="members")
    user: "User" = Relationship(back_populates="memberships")


class OrganizationMemberCreate(SQLModel):
    """Data required to add a member."""
    user_id: UUID
    role: str = Field(default="member", max_length=50)


class OrganizationMemberRead(OrganizationMemberBase):
    """Data returned when reading a member."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class OrganizationMemberUpdate(SQLModel):
    """Fields that can be updated."""
    role: str | None = None
