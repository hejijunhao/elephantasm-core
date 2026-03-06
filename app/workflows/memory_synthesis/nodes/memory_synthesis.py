"""
Memory Synthesis Node

Calls LLM to synthesize memory from collected events.
Core intelligence node - transforms raw events into structured memory.

⚠️ CRITICAL: Uses RLS context for config reads (multi-tenant security).
"""
from uuid import UUID
from langsmith import traceable
from ..state import MemorySynthesisState
from ..prompts.synthesis import build_memory_synthesis_prompt
from app.services.llm import get_llm_client
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context


@traceable(name="synthesize_memory", tags=["llm", "synthesis", "critical"])
async def synthesize_memory_node(state: MemorySynthesisState) -> dict:
    """
    Synthesize memory from pending events via LLM.

    Uses anima's custom temperature and max_tokens from DB config.
    Separates prompt construction (domain logic) from LLM call (infrastructure).

    ⚠️ RLS Context: Config reads use RLS for security.
    Ensures workflow can only access config for anima's user.
    """
    pending_events = state.get("pending_events", [])

    if not pending_events:
        raise ValueError("No pending events to synthesize")

    # Get anima's LLM config from DB (with RLS context)
    # Local import to avoid circular dependency
    from app.domain.synthesis_config_operations import SynthesisConfigOperations

    anima_id = UUID(state["anima_id"])

    # Get user_id for RLS context (lookup without RLS)
    user_id = get_user_id_for_anima(anima_id)

    # Fetch config with RLS context (security enforced by database)
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

    return {
        "llm_response": llm_response,
    }
