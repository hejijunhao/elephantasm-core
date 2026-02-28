"""
Decay score algorithm.

Computes how much a memory has "decayed" (been forgotten) over time.
Incorporates spaced repetition: frequently accessed memories decay slower.

Score ranges from 0.0 (fresh, not decayed) to 1.0 (fully decayed).
Note: Higher decay = worse, so scoring formula uses (1 - decay).
"""

from datetime import datetime, timezone
from typing import Optional
import math


def compute_decay_score(
    memory_time: datetime,
    last_accessed: Optional[datetime] = None,
    access_count: int = 0,
    base_half_life_days: float = 30.0,
    access_boost_factor: float = 1.5,
) -> float:
    """
    Compute decay score with spaced repetition influence.

    Memories accessed more frequently decay slower (longer effective half-life).

    Args:
        memory_time: Original memory creation time
        last_accessed: Last time memory was retrieved (default: memory_time)
        access_count: Number of times memory was accessed
        base_half_life_days: Base decay rate before access boost
        access_boost_factor: Multiplier per access (1.5 = 50% longer half-life per access)

    Returns:
        Score from 0.0 (fresh, not decayed) to 1.0 (fully decayed)

    Examples:
        - just created, 0 accesses → ~0.0
        - 30 days old, 0 accesses (base half-life=30) → ~0.5
        - 30 days old, 2 accesses (effective half-life=67.5 days) → ~0.27
    """
    now = datetime.now(timezone.utc)

    # Handle naive datetimes
    if memory_time.tzinfo is None:
        memory_time = memory_time.replace(tzinfo=timezone.utc)

    # Reference time: last access or creation
    reference_time = last_accessed or memory_time
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    # Spaced repetition: each access extends the half-life
    # Formula: effective_half_life = base * (boost_factor ^ access_count)
    effective_half_life = base_half_life_days * (access_boost_factor**access_count)
    effective_half_life = min(effective_half_life, 365.0)  # Cap at 1 year

    age_seconds = (now - reference_time).total_seconds()
    age_days = age_seconds / 86400

    # Future or just-now timestamps = no decay
    if age_days <= 0:
        return 0.0

    # Decay increases over time (inverse of recency formula)
    # decay = 1 - e^(-decay_rate * age)
    decay_rate = math.log(2) / effective_half_life
    decay = 1 - math.exp(-decay_rate * age_days)

    return max(0.0, min(1.0, decay))
