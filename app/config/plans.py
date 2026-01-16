"""Plan configuration - immutable tier definitions for Elephantasm pricing."""

from dataclasses import dataclass
from typing import Literal

PlanTier = Literal["free", "pro", "team", "enterprise"]
DreamerMode = Literal["manual", "scheduled", "realtime"]


@dataclass(frozen=True)
class PlanConfig:
    """Immutable plan tier configuration."""
    tier: PlanTier
    display_name: str
    price_monthly_cents: int

    # Anima limits
    active_anima_limit: int  # -1 = unlimited
    dormant_anima_limit: int

    # Storage quotas (per month)
    events_per_month: int
    memories_stored: int
    knowledge_items: int

    # Throughput quotas (per month)
    pack_builds_per_month: int
    synthesis_per_month: int

    # Feature flags
    dreamer_enabled: bool
    dreamer_mode: DreamerMode
    pack_size_ceiling_tokens: int
    retention_days: int  # -1 = unlimited

    # Rate limiting
    api_rate_limit_per_second: int  # -1 = custom/unlimited

    # Overages
    allows_overages: bool

    # Team features
    team_seats: int  # -1 = unlimited
    byok_enabled: bool
    audit_logs_enabled: bool


PLANS: dict[str, PlanConfig] = {
    "free": PlanConfig(
        tier="free",
        display_name="Free",
        price_monthly_cents=0,
        active_anima_limit=1,
        dormant_anima_limit=2,
        events_per_month=1_000,
        memories_stored=100,
        knowledge_items=10,
        pack_builds_per_month=500,
        synthesis_per_month=20,
        dreamer_enabled=False,
        dreamer_mode="manual",
        pack_size_ceiling_tokens=2_000,
        retention_days=7,
        api_rate_limit_per_second=5,
        allows_overages=False,
        team_seats=1,
        byok_enabled=False,
        audit_logs_enabled=False,
    ),
    "pro": PlanConfig(
        tier="pro",
        display_name="Pro",
        price_monthly_cents=3900,
        active_anima_limit=10,
        dormant_anima_limit=50,
        events_per_month=100_000,
        memories_stored=10_000,
        knowledge_items=1_000,
        pack_builds_per_month=50_000,
        synthesis_per_month=5_000,
        dreamer_enabled=True,
        dreamer_mode="scheduled",
        pack_size_ceiling_tokens=8_000,
        retention_days=365,
        api_rate_limit_per_second=100,
        allows_overages=True,
        team_seats=1,
        byok_enabled=True,
        audit_logs_enabled=False,
    ),
    "team": PlanConfig(
        tier="team",
        display_name="Team",
        price_monthly_cents=24900,
        active_anima_limit=50,
        dormant_anima_limit=200,
        events_per_month=1_000_000,
        memories_stored=100_000,
        knowledge_items=10_000,
        pack_builds_per_month=500_000,
        synthesis_per_month=50_000,
        dreamer_enabled=True,
        dreamer_mode="realtime",
        pack_size_ceiling_tokens=32_000,
        retention_days=-1,  # Unlimited
        api_rate_limit_per_second=500,
        allows_overages=True,
        team_seats=5,
        byok_enabled=True,
        audit_logs_enabled=True,
    ),
    "enterprise": PlanConfig(
        tier="enterprise",
        display_name="Enterprise",
        price_monthly_cents=0,  # Custom pricing
        active_anima_limit=-1,  # Unlimited
        dormant_anima_limit=-1,
        events_per_month=-1,
        memories_stored=-1,
        knowledge_items=-1,
        pack_builds_per_month=-1,
        synthesis_per_month=-1,
        dreamer_enabled=True,
        dreamer_mode="realtime",
        pack_size_ceiling_tokens=-1,  # Configurable
        retention_days=-1,
        api_rate_limit_per_second=-1,  # Custom
        allows_overages=True,
        team_seats=-1,
        byok_enabled=True,
        audit_logs_enabled=True,
    ),
}


def get_plan(tier: str) -> PlanConfig:
    """Get plan config by tier. Defaults to free if not found."""
    return PLANS.get(tier, PLANS["free"])
