"""Subscription model - billing subscription for organizations."""

from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.organization import Organization
    from app.models.database.user import User


class SubscriptionStatus(str, Enum):
    """Subscription status values."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"


class SubscriptionBase(SQLModel):
    """Shared fields for Subscription model."""
    organization_id: UUID = Field(foreign_key="organizations.id", unique=True, index=True)
    plan_tier: str = Field(default="free", max_length=50, index=True, description="Plan tier: free, pro, team, enterprise")
    status: str = Field(default="active", max_length=50, description="Status: active, past_due, canceled, unpaid")

    # Billing period
    current_period_start: datetime = Field(default_factory=lambda: datetime.utcnow())
    current_period_end: datetime | None = Field(default=None, nullable=True)
    cancel_at_period_end: bool = Field(default=False)

    # Stripe integration (nullable until connected)
    stripe_customer_id: str | None = Field(default=None, max_length=255, index=True, nullable=True)
    stripe_subscription_id: str | None = Field(default=None, max_length=255, index=True, nullable=True)
    stripe_metered_item_id: str | None = Field(default=None, max_length=255, nullable=True)

    # Spending cap (cents, -1 = no cap)
    spending_cap_cents: int = Field(default=-1, description="Spending cap in cents, -1 = no cap")

    # Manual assignment (admin override)
    is_manually_assigned: bool = Field(default=False)
    manually_assigned_by: UUID | None = Field(default=None, foreign_key="users.id", nullable=True)
    manually_assigned_at: datetime | None = Field(default=None, nullable=True)
    manual_assignment_note: str | None = Field(default=None, nullable=True)

    # BYOK flags (actual keys stored encrypted in separate table)
    byok_openai_key_set: bool = Field(default=False)
    byok_anthropic_key_set: bool = Field(default=False)


class Subscription(SubscriptionBase, TimestampMixin, table=True):
    """Subscription entity - billing subscription for an organization."""
    __tablename__ = "subscriptions"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})

    # Relationships
    organization: "Organization" = Relationship(back_populates="subscription")
    assigned_by_user: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Subscription.manually_assigned_by]"}
    )


class SubscriptionCreate(SQLModel):
    """Data required to create a Subscription."""
    organization_id: UUID
    plan_tier: str = Field(default="free", max_length=50)


class SubscriptionRead(SubscriptionBase):
    """Data returned when reading a Subscription."""
    id: UUID
    created_at: datetime
    updated_at: datetime


class SubscriptionUpdate(SQLModel):
    """Fields that can be updated."""
    plan_tier: str | None = None
    status: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_metered_item_id: str | None = None
    spending_cap_cents: int | None = None
    byok_openai_key_set: bool | None = None
    byok_anthropic_key_set: bool | None = None


class SpendingCapUpdate(SQLModel):
    """Update spending cap only."""
    spending_cap_cents: int = Field(ge=-1, description="Spending cap in cents, -1 = no cap")


class AdminPlanAssignment(SQLModel):
    """Admin plan assignment data."""
    plan_tier: str = Field(max_length=50)
    note: str | None = Field(default=None, description="Reason for manual assignment")
