"""
Threshold Gate Node

Evaluates whether accumulation score meets synthesis threshold.
Acts as decision gate: score >= threshold → proceed to synthesis.

⚠️ CRITICAL: Uses RLS context for config updates (multi-tenant security).
"""
import logging
from datetime import datetime, timezone
from uuid import UUID
from langsmith import traceable
from ..state import MemorySynthesisState
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


@traceable(name="check_synthesis_threshold", tags=["decision", "routing"])
def check_synthesis_threshold_node(state: MemorySynthesisState) -> dict:
    """
    Check if synthesis should trigger.

    Requirements:
    1. Accumulation score >= threshold
    2. At least 1 event exists (no synthesis on time alone)

    Reads threshold from anima's DB config (auto-creates with defaults).
    Graph conditional edge will route based on synthesis_triggered field.
    Routing Logic (handled by graph conditional edge):
        synthesis_triggered=True  → "collect_pending_events" (proceed to synthesis)
        synthesis_triggered=False → "skip_synthesis" (exit workflow early)
    """
    # Local import to avoid circular dependency
    from app.domain.synthesis_config_operations import SynthesisConfigOperations

    anima_id = UUID(state["anima_id"])
    score = state.get("accumulation_score", 0.0)
    event_count = state.get("event_count", 0)

    # Get user_id for RLS context (lookup without RLS)
    user_id = get_user_id_for_anima(anima_id)

    # Get anima's threshold from DB (with RLS context)
    with session_with_rls_context(user_id) as session:
        config = SynthesisConfigOperations.get_or_create_default(session, anima_id)
        threshold = config.threshold

    # Guard: Skip if no events (time-only accumulation)
    # Prevents LLM from hallucinating non-existent events
    # IMPORTANT: Reset timestamp to prevent infinite accumulation
    if event_count <= 0:
        logger.info(
            f"Anima {anima_id}: Skipping synthesis (no events, "
            f"score={score:.2f}, hours={state.get('time_factor', 0):.1f})"
        )

        # Reset last_synthesis_check_at to prevent time factor from accumulating infinitely
        with session_with_rls_context(user_id) as session:
            config = SynthesisConfigOperations.get_or_create_default(session, anima_id)
            config.last_synthesis_check_at = datetime.now(timezone.utc)
            session.add(config)
            # Auto-commit on context exit

        return {
            "synthesis_triggered": False,
            "skip_reason": "no_events"
        }

    # Normal threshold check
    triggered = score >= threshold

    if not triggered:
        logger.debug(
            f"Anima {anima_id}: Below threshold "
            f"(score={score:.2f} < {threshold:.2f}, events={event_count})"
        )

    return {
        "synthesis_triggered": triggered,
        "skip_reason": None if triggered else "below_threshold"
    }


def route_after_threshold_check(state: MemorySynthesisState) -> str:
    """
    Conditional routing function for graph edges.

    Used by StateGraph.add_conditional_edges() to determine next node.
    """
    if state.get("synthesis_triggered", False):
        return "collect_pending_events"
    else:
        return "skip_synthesis"
