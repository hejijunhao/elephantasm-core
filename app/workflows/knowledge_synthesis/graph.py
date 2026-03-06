"""
Knowledge Synthesis Workflow Graph

Assembles nodes into LangGraph StateGraph with PostgreSQL checkpointing.
Linear workflow (no threshold gate - always runs to completion).
"""
import asyncio

from langgraph.graph import StateGraph, START, END

from .state import KnowledgeSynthesisState
from .nodes import (
    fetch_memory_node,
    synthesize_knowledge_node,
    persist_knowledge_node,
)
from app.workflows.utils.checkpointer import create_checkpointer


async def build_knowledge_synthesis_graph():
    """
    Construct the knowledge synthesis workflow graph.

    Flow (Linear - No Conditional Routing):
        START
          ↓
        fetch_memory (sync, DB read with RLS)
          ↓
        synthesize_knowledge (async, LLM call)
          ↓
        persist_knowledge (sync, DB write with RLS + audit)
          ↓
        END

    Differences from Memory Synthesis:
    - No accumulation score calculation
    - No threshold gate (always processes to completion)
    - Simpler linear flow (3 nodes vs 5)
    - Skip reasons handled within nodes (don't stop flow)

    Returns:
        Compiled StateGraph with AsyncPostgresSaver checkpointer
    """
    # Initialize workflow
    workflow = StateGraph(KnowledgeSynthesisState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Memory fetch (DB read, RLS context, transient failures possible)
    workflow.add_node(
        "fetch_memory",
        fetch_memory_node,
    )

    # Knowledge synthesis (async LLM call, rate limits/timeouts possible)
    workflow.add_node(
        "synthesize_knowledge",
        synthesize_knowledge_node,
    )

    # Knowledge persistence (DB write, RLS context, atomic transaction)
    workflow.add_node(
        "persist_knowledge",
        persist_knowledge_node,
    )

    # ========================================================================
    # Add Edges (Linear Flow)
    # ========================================================================

    # Static edges (always execute in sequence)
    workflow.add_edge(START, "fetch_memory")
    workflow.add_edge("fetch_memory", "synthesize_knowledge")
    workflow.add_edge("synthesize_knowledge", "persist_knowledge")
    workflow.add_edge("persist_knowledge", END)

    # Note: No conditional routing needed (unlike Memory Synthesis)
    # Skip reasons are informational (stored in state) but don't stop flow
    # Empty extractions result in empty knowledge_ids (valid outcome)

    # ========================================================================
    # Compile with Checkpointer (Two-Phase Connection Strategy)
    # ========================================================================
    # See app/workflows/utils/checkpointer.py for connection details.

    runtime_checkpointer = await create_checkpointer()
    graph = workflow.compile(checkpointer=runtime_checkpointer)

    return graph


# ============================================================================
# Singleton Instance
# ============================================================================

# Note: Graph initialization moved to lazy loading due to async context manager
# Use get_knowledge_synthesis_graph() instead of direct import
_knowledge_synthesis_graph = None
# Lock is event-loop-scoped — only valid when all callers share the same loop.
# Currently safe: graph singletons are only accessed from the main event loop
# (memory/knowledge synthesis schedulers), never from Dreamer's deep sleep thread.
_knowledge_graph_lock = asyncio.Lock()


async def get_knowledge_synthesis_graph():
    """
    Get (or build) the knowledge synthesis graph singleton.

    Lazy initialization pattern for async context manager handling.
    Uses asyncio.Lock to prevent concurrent builds leaking connection pools.

    Usage in API routes or scheduler:
        graph = await get_knowledge_synthesis_graph()
        result = await graph.ainvoke(
            {"memory_id": str(memory_id)},
            config={"configurable": {"thread_id": f"knowledge-{memory_id}"}}
        )

    Thread ID Format:
        "knowledge-{memory_id}" - One thread per Memory (isolated checkpointing)

    Returns:
        Compiled StateGraph with AsyncPostgresSaver checkpointer
    """
    global _knowledge_synthesis_graph
    if _knowledge_synthesis_graph is not None:
        return _knowledge_synthesis_graph
    async with _knowledge_graph_lock:
        if _knowledge_synthesis_graph is None:
            _knowledge_synthesis_graph = await build_knowledge_synthesis_graph()
        return _knowledge_synthesis_graph
