"""
Memory Synthesis (LLM)

Calls LLM to synthesize memory from collected events.
Core intelligence node — transforms raw events into structured memory.

Uses RLS context for config reads (multi-tenant security).
"""
import logging
from typing import Dict, Any, List
from uuid import UUID

from ..prompts.synthesis import build_memory_synthesis_prompt
from app.services.llm import get_llm_client
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context

logger = logging.getLogger(__name__)


async def synthesize_memory(
    anima_id: UUID,
    pending_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Synthesize memory from pending events via LLM.

    Uses anima's custom temperature and max_tokens from DB config.
    Separates prompt construction (domain logic) from LLM call (infrastructure).

    Returns:
        Dict with keys: summary (required), content, importance, confidence (optional)
    """
    if not pending_events:
        raise ValueError("No pending events to synthesize")

    logger.info(f"Synthesizing memory for anima {anima_id} from {len(pending_events)} events")

    # Get anima's LLM config from DB (with RLS context)
    from app.domain.synthesis_config_operations import SynthesisConfigOperations

    user_id = get_user_id_for_anima(anima_id)

    with session_with_rls_context(user_id) as session:
        config = SynthesisConfigOperations.get_or_create_default(session, anima_id)
        temperature = config.temperature
        max_tokens = config.max_tokens

    # Build prompt (workflow-specific domain logic)
    prompt = build_memory_synthesis_prompt(pending_events)

    # Get LLM client (provider selected via config)
    llm_client = get_llm_client()

    # Call LLM with anima-specific parameters (automatic retry logic in client)
    response_text = await llm_client.call(prompt, temperature=temperature, max_tokens=max_tokens)

    # Parse structured response
    llm_response = llm_client.parse_json_response(response_text)

    # Validate required fields
    if "summary" not in llm_response:
        raise ValueError(f"LLM response missing 'summary' field: {llm_response}")

    # Normalize optional fields
    llm_response.setdefault("content", None)
    llm_response.setdefault("importance", None)
    llm_response.setdefault("confidence", None)

    logger.info(f"Memory synthesized for anima {anima_id}: {llm_response['summary'][:80]}")

    return llm_response
