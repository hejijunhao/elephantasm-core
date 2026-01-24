"""Overage pricing configuration for Elephantasm plans."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OverageRate:
    """Overage pricing for a resource type."""
    resource: str
    pro_cents: int
    team_cents: int
    unit_size: int  # e.g., 10_000 events


# Overage rates per resource type
OVERAGE_RATES: dict[str, OverageRate] = {
    "events": OverageRate(resource="events", pro_cents=100, team_cents=50, unit_size=10_000),
    "memories": OverageRate(resource="memories", pro_cents=200, team_cents=100, unit_size=1_000),
    "knowledge": OverageRate(resource="knowledge", pro_cents=500, team_cents=250, unit_size=500),
    "pack_builds": OverageRate(resource="pack_builds", pro_cents=100, team_cents=50, unit_size=10_000),
    "synthesis": OverageRate(resource="synthesis", pro_cents=300, team_cents=150, unit_size=1_000),
    "vector_storage_gb": OverageRate(resource="vector_storage_gb", pro_cents=25, team_cents=15, unit_size=1),
}

# Default spending cap multipliers (relative to base plan price)
SPENDING_CAP_MULTIPLIERS: dict[str, float] = {
    "pro": 3.0,   # 3x base = $117/mo max by default
    "team": 2.0,  # 2x base = $498/mo max by default
}


def calculate_overage_cost(
    resource: str,
    usage: int,
    limit: int,
    plan_tier: str
) -> int:
    """Calculate overage cost in cents for a resource.

    Args:
        resource: Resource type (events, memories, etc.)
        usage: Current usage count
        limit: Plan limit (-1 = unlimited)
        plan_tier: Plan tier (pro, team)

    Returns:
        Overage cost in cents (0 if within limit or no overages)
    """
    if limit == -1:  # Unlimited
        return 0

    if usage <= limit:
        return 0

    rate = OVERAGE_RATES.get(resource)
    if not rate:
        return 0

    overage_amount = usage - limit
    units = (overage_amount + rate.unit_size - 1) // rate.unit_size  # Ceiling division

    if plan_tier == "pro":
        return units * rate.pro_cents
    elif plan_tier == "team":
        return units * rate.team_cents

    return 0  # Free/Enterprise don't have overages this way
