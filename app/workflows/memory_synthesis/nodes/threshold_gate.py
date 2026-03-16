"""
Threshold Gate

Evaluates whether accumulation score meets synthesis threshold.
Acts as decision gate: score >= threshold -> proceed to synthesis.

Uses RLS context for config updates (multi-tenant security).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


@dataclass
class ThresholdGateResult:
    """Result from threshold gate check."""

    synthesis_triggered: bool = False
    skip_reason: str | None = None


def check_synthesis_threshold(
    anima_id: UUID,
    accumulation_score: float,
    event_count: int,
    time_factor: float = 0.0,
) -> ThresholdGateResult:
    """
    Check if synthesis should trigger.

    Requirements:
    1. Accumulation score >= threshold
    2. At least 1 event exists (no synthesis on time alone)

    Reads threshold from anima's DB config (auto-creates with defaults).
    """
    # Local import to avoid circular dependency
    from app.domain.synthesis_config_operations import SynthesisConfigOperations

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
            f"score={accumulation_score:.2f}, hours={time_factor:.1f})"
        )

        # Reset last_synthesis_check_at to prevent time factor from accumulating infinitely
        with session_with_rls_context(user_id) as session:
            config = SynthesisConfigOperations.get_or_create_default(session, anima_id)
            config.last_synthesis_check_at = datetime.now(timezone.utc)
            session.add(config)
            # Auto-commit on context exit

        return ThresholdGateResult(synthesis_triggered=False, skip_reason="no_events")

    # Normal threshold check
    triggered = accumulation_score >= threshold

    if not triggered:
        logger.debug(
            f"Anima {anima_id}: Below threshold "
            f"(score={accumulation_score:.2f} < {threshold:.2f}, events={event_count})"
        )

    return ThresholdGateResult(
        synthesis_triggered=triggered,
        skip_reason=None if triggered else "below_threshold",
    )
