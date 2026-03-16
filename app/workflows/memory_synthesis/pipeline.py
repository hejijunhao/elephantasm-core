"""
Memory Synthesis Pipeline

Native async pipeline replacing LangGraph StateGraph.
Executes 5 sequential steps with a threshold gate:

    1. Calculate accumulation score (sync, DB read)
    2. Check threshold gate (sync, DB read/write)
    3. Collect pending events (sync, DB read)
    4. Synthesize memory via LLM (async)
    5. Persist memory + provenance links (sync, DB write)

Usage:
    from app.workflows.memory_synthesis.pipeline import run_memory_synthesis
    result = await run_memory_synthesis("anima-uuid")
"""
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from app.workflows.pipeline import MemorySynthesisResult
from .nodes import (
    calculate_accumulation_score,
    check_synthesis_threshold,
    collect_pending_events,
    synthesize_memory,
    persist_memory,
)

logger = logging.getLogger(__name__)


async def run_memory_synthesis(anima_id: str) -> MemorySynthesisResult:
    """
    Execute memory synthesis pipeline for an anima.

    Steps:
    1. Calculate accumulation score
    2. Check threshold (gate) — early exit if below threshold or no events
    3. Collect pending events
    4. Synthesize memory via LLM
    5. Persist memory + provenance links

    Args:
        anima_id: UUID string of the anima to synthesize for

    Returns:
        MemorySynthesisResult with synthesis outcome
    """
    start_time = time.perf_counter()
    result = MemorySynthesisResult(
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    anima_uuid = UUID(anima_id)

    try:
        # Step 1: Calculate accumulation score
        score_result = calculate_accumulation_score(anima_uuid)
        result.accumulation_score = score_result.accumulation_score
        result.time_factor = score_result.time_factor
        result.event_factor = score_result.event_factor
        result.token_factor = score_result.token_factor
        result.event_count = score_result.event_count

        # Step 2: Threshold gate
        gate_result = check_synthesis_threshold(
            anima_uuid,
            accumulation_score=score_result.accumulation_score,
            event_count=score_result.event_count,
            time_factor=score_result.time_factor,
        )
        result.synthesis_triggered = gate_result.synthesis_triggered
        result.skip_reason = gate_result.skip_reason

        if not gate_result.synthesis_triggered:
            result.success = True
            result.skipped = True
            result._finalize(start_time)
            return result

        # Step 3: Collect pending events
        pending_events = collect_pending_events(anima_uuid)

        # Step 4: LLM synthesis
        llm_response = await synthesize_memory(anima_uuid, pending_events)

        # Step 5: Persist memory + provenance
        persist_result = persist_memory(anima_uuid, pending_events, llm_response)
        result.memory_id = persist_result.memory_id
        result.provenance_links = persist_result.provenance_links
        result.embedding_generated = persist_result.embedding_generated

        result.success = True
        result.synthesis_triggered = True

    except Exception as e:
        logger.error(f"Memory synthesis failed for anima {anima_id}: {e}", exc_info=True)
        result.error = str(e)

    result._finalize(start_time)
    return result
