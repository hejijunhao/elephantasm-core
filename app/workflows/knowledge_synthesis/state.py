"""
Knowledge Synthesis State Schema

Defines the shared state (memory) for the Knowledge Synthesis LangGraph workflow.
Stores raw data, not formatted text (prompts formatted on-demand).

Workflow Flow:
    START (input: memory_id)
      ↓
    fetch_memory → memory_data, source_events
      ↓
    synthesize_knowledge → llm_response (array)
      ↓
    persist_knowledge → knowledge_ids, deleted_count
      ↓
    END
"""
from typing_extensions import TypedDict, NotRequired
from typing import List, Dict, Any


class KnowledgeSynthesisState(TypedDict):
    """
    State for knowledge synthesis workflow (per-memory invocation).

    Following LangGraph best practices:
    - Store raw data, not formatted prompts
    - Use NotRequired for fields populated during execution
    - Keep state serializable for checkpointing
    - One workflow run per Memory (no accumulation)

    Input:
        memory_id: UUID of Memory to synthesize Knowledge from

    Output:
        knowledge_ids: List of created Knowledge UUIDs
        deleted_count: Number of previous Knowledge items replaced (deduplication)
    """

    # ========================================================================
    # INPUT (Required at START)
    # ========================================================================

    memory_id: str  # UUID of Memory to process (single source)

    # ========================================================================
    # FETCH MEMORY NODE (Populated by fetch_memory_node)
    # ========================================================================

    memory_data: NotRequired[Dict[str, Any]]  # Serialized Memory (summary, content, importance, etc.)
    source_events: NotRequired[List[Dict[str, Any]]]  # Optional: Events that created this Memory (provenance context)

    # ========================================================================
    # SYNTHESIS NODE (Populated by synthesize_knowledge_node)
    # ========================================================================

    llm_response: NotRequired[List[Dict[str, Any]]]  # Array of Knowledge items from LLM
    # Expected structure per item:
    # {
    #   "knowledge_type": "FACT" | "CONCEPT" | "METHOD" | "PRINCIPLE" | "EXPERIENCE",
    #   "content": "Complete standalone statement",
    #   "summary": "Brief one-line summary",
    #   "topic": "Semantic category/namespace"
    # }

    # ========================================================================
    # PERSISTENCE NODE (Populated by persist_knowledge_node)
    # ========================================================================

    knowledge_ids: NotRequired[List[str]]  # Created Knowledge UUIDs (may be empty if no extractions)
    deleted_count: NotRequired[int]  # Previous Knowledge items deleted (deduplication)
    created_count: NotRequired[int]  # New Knowledge items created (same as len(knowledge_ids))

    # ========================================================================
    # ERROR HANDLING & CONTROL FLOW
    # ========================================================================

    error: NotRequired[str]  # Error message if any node failed
    skip_reason: NotRequired[str | None]  # Why synthesis was skipped:
    # - "invalid_memory" (Memory not found or deleted)
    # - "no_extractions" (LLM returned empty array)
    # - None (normal execution)

    # ========================================================================
    # METADATA (Timestamps)
    # ========================================================================

    started_at: NotRequired[str]  # ISO timestamp when workflow started
    completed_at: NotRequired[str]  # ISO timestamp when workflow completed
    duration_ms: NotRequired[float]  # Total execution time in milliseconds


# ============================================================================
# State Field Descriptions
# ============================================================================

"""
Field Lifecycle:

1. START:
   - memory_id: Set by caller (API endpoint or scheduler)

2. fetch_memory_node:
   - Reads: memory_id
   - Writes: memory_data, source_events (optional), error, skip_reason
   - Conditions:
     * Success: memory_data populated
     * Skip: skip_reason="invalid_memory" if Memory not found/deleted
     * Error: error set on DB failure

3. synthesize_knowledge_node:
   - Reads: memory_data
   - Writes: llm_response, error, skip_reason
   - Conditions:
     * Success: llm_response is array (may be empty)
     * Skip: skip_reason="no_extractions" if empty array
     * Error: error set on LLM failure or parse error

4. persist_knowledge_node:
   - Reads: llm_response, memory_id, memory_data (for anima_id)
   - Writes: knowledge_ids, deleted_count, created_count, error
   - Conditions:
     * Success: knowledge_ids populated (may be empty)
     * Error: error set on DB failure

5. END:
   - Final state available for inspection/logging

Design Notes:

- **No Threshold Gate**: Unlike Memory Synthesis, this workflow always runs
  to completion. No accumulation score or conditional routing.

- **Deduplication Strategy**: Delete existing Knowledge with source_id=memory_id
  before inserting new items. This ensures re-synthesis replaces old extractions.

- **Empty Extractions Valid**: LLM may return empty array for minimal Memories
  (e.g., "Hello", "Thanks!"). This is not an error, just a no-op.

- **Source Events Optional**: May include Events that created the Memory for
  additional context in LLM prompt (future enhancement).

- **Provenance Automatic**: All created Knowledge items get source_id=memory_id
  and source_type=EXTERNAL (from Memory, not internal reflection).

- **Audit Logging**: Each created Knowledge triggers audit log entry
  (action=CREATE, triggered_by="knowledge_synthesis_workflow").
"""
