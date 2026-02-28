"""Synthesis-related metrics and calculations for memory synthesis workflow.

Domain layer: Pure business logic for computing synthesis scores and metrics.
Reusable across API routes, schedulers, workflows, and CLI tools.

Pattern: Sync operations with explicit session passing (Marlin pattern).
"""

from datetime import datetime, timezone
from typing import Dict
from uuid import UUID

from sqlmodel import Session

from app.domain.anima_operations import AnimaOperations
from app.domain.event_operations import EventOperations
from app.domain.memory_operations import MemoryOperations


def compute_accumulation_score(session: Session, anima_id: UUID) -> Dict:
    """
    Calculate accumulation score for memory synthesis trigger.

    Uses three-factor formula:
    score = (hours × time_weight) + (events × event_weight) + (tokens × token_weight)

    Args:
        session: Database session
        anima_id: UUID of anima to compute score for

    Returns:
        {
            "accumulation_score": float,  # Total weighted score
            "time_factor": float,          # Hours × time_weight
            "event_factor": float,         # Events × event_weight
            "token_factor": float,         # Tokens × token_weight
            "event_count": int,            # Raw event count
            "hours_since_last": float      # Hours since last memory
        }

    Notes:
        - Baseline timestamp: last memory creation time, or anima.created_at if no memories
        - Token estimation: event_count × 100 (rough approximation)
        - Timezone aware: Uses datetime.now(timezone.utc) for calculations
    """
    # Local import to avoid circular dependency
    # (synthesis_config_operations -> workflows -> nodes -> synthesis_config_operations)
    from app.domain.synthesis_config_operations import SynthesisConfigOperations

    # Get per-anima config (auto-creates with defaults if missing)
    config = SynthesisConfigOperations.get_or_create_default(session, anima_id)

    # Determine baseline timestamp (most recent of: last_synthesis_check_at, last_memory, anima.created_at)
    # This ensures clock resets when we skip synthesis due to zero events
    baseline_time = None

    # Option 1: last_synthesis_check_at (most recent check, even if skipped)
    if config.last_synthesis_check_at:
        baseline_time = config.last_synthesis_check_at
        # Ensure timezone awareness
        if baseline_time.tzinfo is None:
            baseline_time = baseline_time.replace(tzinfo=timezone.utc)

    # Option 2: last memory time (most recent synthesis that created memory)
    last_memory_time = MemoryOperations.get_last_memory_time(session, anima_id)
    if last_memory_time:
        # Ensure timezone awareness before comparison
        if last_memory_time.tzinfo is None:
            last_memory_time = last_memory_time.replace(tzinfo=timezone.utc)

        if not baseline_time or last_memory_time > baseline_time:
            baseline_time = last_memory_time

    # Fallback: anima creation time
    if not baseline_time:
        anima = AnimaOperations.get_by_id(session, anima_id)
        if anima:
            baseline_time = anima.created_at
            # Ensure timezone awareness
            if baseline_time.tzinfo is None:
                baseline_time = baseline_time.replace(tzinfo=timezone.utc)
        else:
            # Ultimate fallback (shouldn't happen in normal operation)
            baseline_time = datetime(2000, 1, 1, tzinfo=timezone.utc)

    # Calculate time factor (hours since baseline × weight)
    now = datetime.now(timezone.utc)
    hours_since_last = (now - baseline_time).total_seconds() / 3600
    time_factor = hours_since_last * config.time_weight

    # Calculate event factor (event count × weight)
    event_count = EventOperations.count_since(session, anima_id, baseline_time)
    event_factor = event_count * config.event_weight

    # Calculate token factor (estimated tokens × weight)
    # Rough estimate: 100 tokens per event (same as workflow node)
    token_estimate = event_count * 100
    token_factor = token_estimate * config.token_weight

    # Total accumulation score
    accumulation_score = time_factor + event_factor + token_factor

    return {
        "accumulation_score": accumulation_score,
        "time_factor": time_factor,
        "event_factor": event_factor,
        "token_factor": token_factor,
        "event_count": event_count,
        "hours_since_last": hours_since_last,
    }
