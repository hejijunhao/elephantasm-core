"""
Memory Synthesis State Schema

Defines the shared state (memory) for the LangGraph workflow.
Stores raw data, not formatted text (prompts formatted on-demand).
"""
from typing_extensions import TypedDict, NotRequired
from typing import List, Dict, Any


class MemorySynthesisState(TypedDict):
    """
    State for memory synthesis workflow (per-anima thread).

    Following LangGraph best practices:
    - Store raw data, not formatted prompts
    - Use NotRequired for fields populated during execution
    - Keep state serializable for checkpointing
    """

    anima_id: str  # UUID of anima being processed
    accumulation_score: NotRequired[float]  # Composite score (time + events + tokens)
    time_factor: NotRequired[float]         # Hours since last memory
    event_factor: NotRequired[float]        # Event count contribution
    token_factor: NotRequired[float]        # Estimated token count contribution
    event_count: NotRequired[int]           # Raw event count
    synthesis_triggered: NotRequired[bool]  # Whether threshold met
    skip_reason: NotRequired[str | None]    # Why synthesis skipped: "no_events" | "below_threshold" | None
    pending_events: NotRequired[List[Dict[str, Any]]]  # Serialized events (raw)
    llm_response: NotRequired[Dict[str, Any]]  # Raw LLM output (not formatted)
    memory_id: NotRequired[str]                   # Created memory UUID
    provenance_links: NotRequired[List[str]]      # Created MemoryEvent link IDs
    error: NotRequired[str]  # Error message if node failed
    started_at: NotRequired[str]    # ISO timestamp
    completed_at: NotRequired[str]  # ISO timestamp
