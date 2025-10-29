"""
Accumulation Score Calculation Node

Calculates composite score representing "weight" of unprocessed events.
Higher score = more accumulated experience = higher synthesis priority.
"""
from datetime import datetime
from uuid import UUID
from ..state import MemorySynthesisState
from ..config import TIME_WEIGHT, EVENT_WEIGHT, TOKEN_WEIGHT
from app.domain.memory_operations import MemoryOperations
from app.domain.event_operations import EventOperations
from app.domain.anima_operations import AnimaOperations
from app.core.database import get_db_session


def calculate_accumulation_score_node(state: MemorySynthesisState) -> dict:
    """
    Calculate composite accumulation score for memory synthesis.
    Formula: score = (hours × TIME_WEIGHT) + (events × EVENT_WEIGHT) + (tokens × TOKEN_WEIGHT)
    """
    anima_id = UUID(state["anima_id"])

    with get_db_session() as session:
        # Get baseline timestamp (last memory or anima creation)
        baseline_time = _get_baseline_timestamp(session, anima_id)

        # Get event count since baseline
        event_count = EventOperations.count_since(session, anima_id, baseline_time)

        if event_count == 0:
            return _zero_score_state()

        # Calculate composite score
        return _calculate_composite_score(baseline_time, event_count)


# ============================================================================
# Helper Functions
# ============================================================================

def _get_baseline_timestamp(session, anima_id: UUID) -> datetime:
    # Get baseline timestamp for accumulation calculation.
    # Returns last memory timestamp, or anima creation time if no memories exist.
    last_memory_time = MemoryOperations.get_last_memory_time(session, anima_id)

    if last_memory_time:
        return last_memory_time

    # Fallback: anima creation time
    anima = AnimaOperations.get_by_id(session, anima_id)
    if not anima:
        raise ValueError(f"Anima {anima_id} not found")

    return anima.created_at


def _zero_score_state() -> dict:
    # Return state update for zero accumulation (no events).
    return {
        "accumulation_score": 0.0,
        "time_factor": 0.0,
        "event_factor": 0.0,
        "token_factor": 0.0,
        "event_count": 0,
    }


def _calculate_composite_score(baseline_time: datetime, event_count: int) -> dict:
    # Calculate weighted composite score from time, events, and estimated tokens.
    # Time component
    hours_elapsed = (datetime.utcnow() - baseline_time).total_seconds() / 3600
    time_score = hours_elapsed * TIME_WEIGHT

    # Event component
    event_score = event_count * EVENT_WEIGHT

    # Token component (estimate: avg 100 tokens per event)
    estimated_tokens = event_count * 100
    token_score = estimated_tokens * TOKEN_WEIGHT

    # Composite
    composite_score = time_score + event_score + token_score

    return {
        "accumulation_score": composite_score,
        "time_factor": time_score,
        "event_factor": event_score,
        "token_factor": token_score,
        "event_count": event_count,
    }
