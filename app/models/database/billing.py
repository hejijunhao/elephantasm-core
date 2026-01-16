"""Billing event model - audit log for billing-related events."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel


class BillingEventType(str, Enum):
    """Types of billing events."""
    # Subscription lifecycle
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELED = "subscription.canceled"

    # Plan changes
    PLAN_CHANGED = "plan.changed"
    PLAN_DOWNGRADED = "plan.downgraded"
    PLAN_UPGRADED = "plan.upgraded"

    # Payments
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"

    # Overages
    OVERAGE_BILLED = "overage.billed"
    OVERAGE_WARNING = "overage.warning"

    # Spending caps
    SPENDING_CAP_SET = "spending_cap.set"
    SPENDING_CAP_REACHED = "spending_cap.reached"
    SPENDING_CAP_WARNING = "spending_cap.warning"

    # Admin actions
    MANUAL_ASSIGNMENT = "manual.assignment"
    MANUAL_CREDIT = "manual.credit"

    # BYOK
    BYOK_KEY_SET = "byok.key_set"
    BYOK_KEY_REMOVED = "byok.key_removed"

    # Referrals
    REFERRAL_CREDIT_APPLIED = "referral.credit_applied"
    REFERRAL_EARNED = "referral.earned"

    # Period events
    PERIOD_STARTED = "period.started"
    PERIOD_ENDED = "period.ended"


class BillingEventBase(SQLModel):
    """Shared fields for BillingEvent model."""
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    event_type: str = Field(max_length=100, index=True)
    description: str

    # Before/after state
    previous_value: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    new_value: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    # External references
    stripe_event_id: str | None = Field(default=None, max_length=255, index=True, nullable=True)

    # Actor (for manual actions)
    actor_user_id: UUID | None = Field(default=None, foreign_key="users.id", nullable=True)


class BillingEvent(BillingEventBase, table=True):
    """Billing event audit log entry."""
    __tablename__ = "billing_events"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BillingEventCreate(SQLModel):
    """Data required to create a BillingEvent."""
    organization_id: UUID
    event_type: str = Field(max_length=100)
    description: str
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    stripe_event_id: str | None = None
    actor_user_id: UUID | None = None


class BillingEventRead(BillingEventBase):
    """Data returned when reading a BillingEvent."""
    id: UUID
    created_at: datetime
