"""
Recency score algorithm.

Computes how "fresh" a memory is using exponential decay.
Score ranges from 1.0 (just created) to ~0.0 (ancient).
"""

from datetime import datetime, timezone
from typing import Optional
import math


def compute_recency_score(
    memory_time: datetime,
    reference_time: Optional[datetime] = None,
    half_life_days: float = 7.0,
) -> float:
    """
    Compute recency score using exponential decay.

    Args:
        memory_time: When the memory was created/updated
        reference_time: Point in time to compute from (default: now UTC)
        half_life_days: Days until score drops to 0.5

    Returns:
        Score from 0.0 (ancient) to 1.0 (just now)

    Examples:
        - memory_time = now → 1.0
        - memory_time = 7 days ago (with half_life=7) → 0.5
        - memory_time = 14 days ago (with half_life=7) → 0.25
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    # Handle naive datetimes by assuming UTC
    if memory_time.tzinfo is None:
        memory_time = memory_time.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    age_seconds = (reference_time - memory_time).total_seconds()
    age_days = age_seconds / 86400

    # Future timestamps get max score
    if age_days <= 0:
        return 1.0

    # Exponential decay: score = 2^(-age/half_life)
    # Equivalent to: score = e^(-decay_rate * age)
    decay_rate = math.log(2) / half_life_days
    score = math.exp(-decay_rate * age_days)

    return max(0.0, min(1.0, score))
