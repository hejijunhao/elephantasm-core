"""
Knowledge Synthesis Pipeline

Native async pipeline replacing LangGraph StateGraph.
Executes 3 sequential steps (no threshold gate):

    1. Fetch memory (sync, DB read with RLS bypass)
    2. Synthesize knowledge via LLM (async)
    3. Persist knowledge items + audit logs (sync, DB write)

Usage:
    from app.workflows.knowledge_synthesis.pipeline import run_knowledge_synthesis
    result = await run_knowledge_synthesis("memory-uuid")
"""
import logging
import time
from datetime import datetime, timezone

from app.workflows.pipeline import KnowledgeSynthesisResult
from .nodes import (
    fetch_memory,
    synthesize_knowledge,
    persist_knowledge,
)

logger = logging.getLogger(__name__)


async def run_knowledge_synthesis(memory_id: str) -> KnowledgeSynthesisResult:
    """
    Extract Knowledge items from a Memory via LLM.

    Steps:
    1. Fetch memory (with RLS bypass for user resolution)
    2. Synthesize knowledge via LLM
    3. Persist knowledge items + audit logs

    Args:
        memory_id: UUID string of the memory to synthesize from

    Returns:
        KnowledgeSynthesisResult with created knowledge IDs and counts
    """
    start_time = time.perf_counter()
    result = KnowledgeSynthesisResult(
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        # Step 1: Fetch memory
        fetch_result = fetch_memory(memory_id)

        if fetch_result.error or fetch_result.skip_reason:
            result.error = fetch_result.error
            result.skip_reason = fetch_result.skip_reason
            # Still mark as success if it's just a skip (invalid memory is expected)
            result.success = fetch_result.error is None or fetch_result.skip_reason is not None
            result._finalize(start_time)
            return result

        # Step 2: LLM synthesis
        llm_result = await synthesize_knowledge(fetch_result.memory_data)

        if llm_result.error or llm_result.skip_reason:
            result.error = llm_result.error
            result.skip_reason = llm_result.skip_reason
            result.success = llm_result.error is None or llm_result.skip_reason is not None
            result._finalize(start_time)
            return result

        # Step 3: Persist knowledge
        anima_id = fetch_result.memory_data["anima_id"]
        result.anima_id = anima_id
        persist_result = persist_knowledge(memory_id, anima_id, llm_result.llm_response)

        result.knowledge_ids = persist_result.knowledge_ids
        result.deleted_count = persist_result.deleted_count
        result.created_count = persist_result.created_count
        result.error = persist_result.error
        result.success = persist_result.error is None

    except Exception as e:
        logger.error(f"Knowledge synthesis failed for memory {memory_id}: {e}", exc_info=True)
        result.error = str(e)

    result._finalize(start_time)
    return result
