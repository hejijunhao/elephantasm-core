"""
Memory Synthesis Node

Calls LLM to synthesize memory from collected events.
Core intelligence node - transforms raw events into structured memory.
"""
from ..state import MemorySynthesisState
from ..prompts.synthesis import build_memory_synthesis_prompt
from app.services.llm import get_llm_client


async def synthesize_memory_node(state: MemorySynthesisState) -> dict:
    """
    Synthesize memory from pending events via LLM.

    Separates prompt construction (domain logic) from LLM call (infrastructure).
    """
    pending_events = state.get("pending_events", [])

    if not pending_events:
        raise ValueError("No pending events to synthesize")

    # Build prompt (workflow-specific domain logic)
    prompt = build_memory_synthesis_prompt(pending_events)

    # Get LLM client (provider selected via config)
    llm_client = get_llm_client()

    # Call LLM (automatic retry logic in client)
    response_text = await llm_client.call(prompt)

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
