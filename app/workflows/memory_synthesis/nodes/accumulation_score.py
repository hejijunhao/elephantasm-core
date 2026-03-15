"""
Accumulation Score Calculation

Calculates composite score representing "weight" of unprocessed events.
Higher score = more accumulated experience = higher synthesis priority.

Uses RLS context for multi-tenant security (read operations).
"""
import logging
from dataclasses import dataclass
from uuid import UUID

from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context
from app.domain.synthesis_metrics import compute_accumulation_score

logger = logging.getLogger(__name__)


@dataclass
class AccumulationScoreResult:
    """Result from accumulation score calculation."""

    accumulation_score: float = 0.0
    time_factor: float = 0.0
    event_factor: float = 0.0
    token_factor: float = 0.0
    event_count: int = 0


def calculate_accumulation_score(anima_id: UUID) -> AccumulationScoreResult:
    """
    Calculate composite accumulation score for memory synthesis.

    Delegates to domain layer helper for calculation logic.
    Formula: score = (hours * time_weight) + (events * event_weight) + (tokens * token_weight)

    RLS Context: Score calculation uses RLS for security.
    """
    logger.info(f"Calculating accumulation score for anima {anima_id}")

    user_id = get_user_id_for_anima(anima_id)

    with session_with_rls_context(user_id) as session:
        result = compute_accumulation_score(session, anima_id)

    return AccumulationScoreResult(
        accumulation_score=result["accumulation_score"],
        time_factor=result["time_factor"],
        event_factor=result["event_factor"],
        token_factor=result["token_factor"],
        event_count=result["event_count"],
    )
