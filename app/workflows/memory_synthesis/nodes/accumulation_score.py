"""
Accumulation Score Calculation Node

Calculates composite score representing "weight" of unprocessed events.
Higher score = more accumulated experience = higher synthesis priority.

Refactored to use domain layer helper for DRY principle and timezone safety.

⚠️ CRITICAL: Uses RLS context for multi-tenant security (read operations).
"""
from uuid import UUID
from langsmith import traceable

from ..state import MemorySynthesisState
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context
from app.domain.synthesis_metrics import compute_accumulation_score


@traceable(name="calculate_accumulation_score", tags=["scoring", "db_read"])
def calculate_accumulation_score_node(state: MemorySynthesisState) -> dict:
    """
    Calculate composite accumulation score for memory synthesis.

    Delegates to domain layer helper for calculation logic.
    Formula: score = (hours × time_weight) + (events × event_weight) + (tokens × token_weight)

    ⚠️ RLS Context: Score calculation uses RLS for security.
    Ensures workflow can only access data for anima's user.

    Returns:
        State update with accumulation_score, time_factor, event_factor, token_factor, event_count
    """
    anima_id = UUID(state["anima_id"])

    # Get user_id for RLS context (lookup without RLS)
    user_id = get_user_id_for_anima(anima_id)

    # Calculate score with RLS context (security enforced by database)
    with session_with_rls_context(user_id) as session:
        # Use domain helper for calculation (handles config, baseline, scoring)
        result = compute_accumulation_score(session, anima_id)

    # Return only fields needed for state update
    return {
        "accumulation_score": result["accumulation_score"],
        "time_factor": result["time_factor"],
        "event_factor": result["event_factor"],
        "token_factor": result["token_factor"],
        "event_count": result["event_count"],
    }
