"""Usage tracking models - real-time counters and historical snapshots."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.database.mixins.timestamp import TimestampMixin


# --- Usage Period (Historical Snapshot) ---

class UsagePeriodBase(SQLModel):
    """Shared fields for UsagePeriod model."""
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)

    # Period boundaries
    period_start: date
    period_end: date

    # Snapshot at period end
    plan_tier: str = Field(max_length=50)

    # Anima counts
    active_anima_count: int = Field(default=0)
    dormant_anima_count: int = Field(default=0)

    # Usage counts (cumulative for period)
    events_created: int = Field(default=0)
    memories_stored: int = Field(default=0)
    knowledge_items: int = Field(default=0)
    pack_builds: int = Field(default=0)
    synthesis_runs: int = Field(default=0)
    vector_storage_bytes: int = Field(default=0, sa_type=BigInteger)

    # Calculated overages
    overage_cents: int = Field(default=0)

    # Billing status
    is_billed: bool = Field(default=False)
    billed_at: datetime | None = Field(default=None, nullable=True)


class UsagePeriod(UsagePeriodBase, table=True):
    """Usage period snapshot for billing history."""
    __tablename__ = "usage_periods"
    __table_args__ = (
        UniqueConstraint("organization_id", "period_start", name="uq_usage_period_org_start"),
    )

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UsagePeriodRead(UsagePeriodBase):
    """Data returned when reading a UsagePeriod."""
    id: UUID
    created_at: datetime


# --- Usage Counter (Real-time) ---

class UsageCounterBase(SQLModel):
    """Shared fields for UsageCounter model."""
    organization_id: UUID = Field(foreign_key="organizations.id", unique=True, index=True)

    # Current period
    period_start: date

    # Counters (incremented atomically)
    events_created: int = Field(default=0)
    pack_builds: int = Field(default=0)
    synthesis_runs: int = Field(default=0)

    # Storage (point-in-time, not cumulative)
    memories_stored: int = Field(default=0)
    knowledge_items: int = Field(default=0)
    vector_storage_bytes: int = Field(default=0, sa_type=BigInteger)

    # Active anima tracking (computed daily via background job)
    active_anima_count: int = Field(default=0)
    dormant_anima_count: int = Field(default=0)
    last_anima_check: datetime = Field(default_factory=datetime.utcnow)


class UsageCounter(UsageCounterBase, table=True):
    """Real-time usage counters (reset monthly)."""
    __tablename__ = "usage_counters"

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UsageCounterRead(UsageCounterBase):
    """Data returned when reading a UsageCounter."""
    id: UUID
    updated_at: datetime


class UsageSummaryRead(SQLModel):
    """Aggregated usage summary with limit comparisons."""
    plan_tier: str
    period_start: date

    # Current usage
    events_created: int
    events_limit: int
    memories_stored: int
    memories_limit: int
    knowledge_items: int
    knowledge_limit: int
    pack_builds: int
    pack_builds_limit: int
    synthesis_runs: int
    synthesis_limit: int

    # Anima usage
    active_anima_count: int
    active_anima_limit: int
    dormant_anima_count: int
    dormant_anima_limit: int

    # Overage info
    total_overage_cents: int
    spending_cap_cents: int
    spending_cap_remaining_cents: int
    is_hard_capped: bool


# --- Limit Status DTOs ---

class LimitStatusRead(SQLModel):
    """Status of a single resource limit."""
    resource: str
    current: int
    limit: int  # -1 = unlimited
    is_exceeded: bool
    allows_overages: bool
    overage_amount: int
    overage_cost_cents: int


class PlanLimitsSummaryRead(SQLModel):
    """Summary of all plan limits and current usage."""
    plan_tier: str
    limits: dict[str, LimitStatusRead]
    total_overage_cents: int
    spending_cap_cents: int  # -1 = no cap
    spending_cap_remaining_cents: int  # -1 = no cap
    is_hard_capped: bool  # True if free tier and any limit exceeded
