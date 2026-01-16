"""Plans API endpoints (public).

Returns plan tier information without authentication.
Used for pricing page and plan comparison UI.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config.plans import PLANS, get_plan, PlanConfig


router = APIRouter(prefix="/plans", tags=["plans"])


class PlanFeatures(BaseModel):
    """Feature flags for a plan."""
    dreamer_enabled: bool
    dreamer_mode: str
    byok_enabled: bool
    audit_logs_enabled: bool
    allows_overages: bool


class PlanLimits(BaseModel):
    """Resource limits for a plan."""
    active_anima_limit: int
    dormant_anima_limit: int
    events_per_month: int
    memories_stored: int
    knowledge_items: int
    pack_builds_per_month: int
    synthesis_per_month: int
    pack_size_ceiling_tokens: int
    retention_days: int
    api_rate_limit_per_second: int
    team_seats: int


class PlanRead(BaseModel):
    """Full plan information for API response."""
    tier: str
    display_name: str
    price_monthly_cents: int
    price_monthly_dollars: float
    features: PlanFeatures
    limits: PlanLimits


class PlanComparisonRead(BaseModel):
    """Plan comparison summary for pricing page."""
    tier: str
    display_name: str
    price_monthly_dollars: float
    # Key differentiators
    active_animas: str  # "1" or "10" or "Unlimited"
    events_per_month: str
    memories: str
    dreamer: str  # "Manual only" or "Scheduled" or "Realtime"
    team_seats: str
    byok: bool
    audit_logs: bool
    allows_overages: bool


def _format_limit(value: int) -> str:
    """Format limit value for display."""
    if value == -1:
        return "Unlimited"
    if value >= 1_000_000:
        return f"{value // 1_000_000}M"
    if value >= 1_000:
        return f"{value // 1_000}K"
    return str(value)


def _plan_to_read(plan: PlanConfig) -> PlanRead:
    """Convert PlanConfig to PlanRead."""
    return PlanRead(
        tier=plan.tier,
        display_name=plan.display_name,
        price_monthly_cents=plan.price_monthly_cents,
        price_monthly_dollars=plan.price_monthly_cents / 100,
        features=PlanFeatures(
            dreamer_enabled=plan.dreamer_enabled,
            dreamer_mode=plan.dreamer_mode,
            byok_enabled=plan.byok_enabled,
            audit_logs_enabled=plan.audit_logs_enabled,
            allows_overages=plan.allows_overages,
        ),
        limits=PlanLimits(
            active_anima_limit=plan.active_anima_limit,
            dormant_anima_limit=plan.dormant_anima_limit,
            events_per_month=plan.events_per_month,
            memories_stored=plan.memories_stored,
            knowledge_items=plan.knowledge_items,
            pack_builds_per_month=plan.pack_builds_per_month,
            synthesis_per_month=plan.synthesis_per_month,
            pack_size_ceiling_tokens=plan.pack_size_ceiling_tokens,
            retention_days=plan.retention_days,
            api_rate_limit_per_second=plan.api_rate_limit_per_second,
            team_seats=plan.team_seats,
        ),
    )


def _plan_to_comparison(plan: PlanConfig) -> PlanComparisonRead:
    """Convert PlanConfig to PlanComparisonRead."""
    # Format dreamer mode for display
    dreamer_display = {
        "manual": "Manual only",
        "scheduled": "Scheduled",
        "realtime": "Realtime",
    }.get(plan.dreamer_mode, plan.dreamer_mode)

    if not plan.dreamer_enabled:
        dreamer_display = "Not available"

    return PlanComparisonRead(
        tier=plan.tier,
        display_name=plan.display_name,
        price_monthly_dollars=plan.price_monthly_cents / 100,
        active_animas=_format_limit(plan.active_anima_limit),
        events_per_month=_format_limit(plan.events_per_month),
        memories=_format_limit(plan.memories_stored),
        dreamer=dreamer_display,
        team_seats=_format_limit(plan.team_seats),
        byok=plan.byok_enabled,
        audit_logs=plan.audit_logs_enabled,
        allows_overages=plan.allows_overages,
    )


@router.get(
    "",
    response_model=List[PlanRead],
    summary="List all plans"
)
async def list_plans() -> List[PlanRead]:
    """
    Get all available plans.

    Returns full plan details including features and limits.
    Public endpoint - no authentication required.
    """
    return [_plan_to_read(plan) for plan in PLANS.values()]


@router.get(
    "/compare",
    response_model=List[PlanComparisonRead],
    summary="Plan comparison"
)
async def compare_plans() -> List[PlanComparisonRead]:
    """
    Get plan comparison summary.

    Returns simplified view for pricing page comparison.
    Public endpoint - no authentication required.
    """
    # Order: free, pro, team, enterprise
    order = ["free", "pro", "team", "enterprise"]
    return [_plan_to_comparison(PLANS[tier]) for tier in order if tier in PLANS]


@router.get(
    "/{tier}",
    response_model=PlanRead,
    summary="Get plan by tier"
)
async def get_plan_by_tier(tier: str) -> PlanRead:
    """
    Get specific plan details by tier.

    Args:
        tier: Plan tier (free, pro, team, enterprise)

    Returns:
        Full plan details

    Raises:
        404: If tier not found
    """
    if tier not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan tier '{tier}' not found. Available: {list(PLANS.keys())}"
        )

    return _plan_to_read(PLANS[tier])
