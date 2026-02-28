"""
Memory Synthesis Workflow Graph

Assembles nodes into LangGraph StateGraph with PostgreSQL checkpointing.
"""
import asyncio

from langgraph.graph import StateGraph, START, END

from .state import MemorySynthesisState
from .nodes import (
    calculate_accumulation_score_node,
    check_synthesis_threshold_node,
    route_after_threshold_check,
    collect_pending_events_node,
    synthesize_memory_node,
    persist_memory_node,
)
from app.workflows.utils.checkpointer import create_checkpointer


async def build_memory_synthesis_graph():
    """
    Construct the memory synthesis workflow graph.

    Flow:
        START
          ↓
        calculate_accumulation_score (sync, DB read)
          ↓
        check_synthesis_threshold (pure, routing decision)
          ↓ (conditional)
          ├─ triggered=True  → collect_pending_events
          └─ triggered=False → END (skip synthesis)
               ↓
        collect_pending_events (sync, DB read)
          ↓
        synthesize_memory (async, LLM call)
          ↓
        persist_memory (sync, DB write)
          ↓
        END

    Returns:
        Compiled StateGraph with AsyncPostgresSaver checkpointer
    """
    # Initialize workflow
    workflow = StateGraph(MemorySynthesisState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Accumulation score (DB read, transient failures possible)
    workflow.add_node(
        "calculate_accumulation_score",
        calculate_accumulation_score_node,
    )

    # Threshold check (pure function, routing decision)
    workflow.add_node(
        "check_synthesis_threshold",
        check_synthesis_threshold_node,
    )

    # Event collection (DB read, transient failures possible)
    workflow.add_node(
        "collect_pending_events",
        collect_pending_events_node,
    )

    # Memory synthesis (async LLM call, rate limits/timeouts possible)
    workflow.add_node(
        "synthesize_memory",
        synthesize_memory_node,
    )

    # Memory persistence (DB write, transient failures possible)
    workflow.add_node(
        "persist_memory",
        persist_memory_node,
    )

    # ========================================================================
    # Add Edges
    # ========================================================================

    # Static edges (always execute)
    workflow.add_edge(START, "calculate_accumulation_score")
    workflow.add_edge("calculate_accumulation_score", "check_synthesis_threshold")

    # Conditional edge: threshold check routes based on score
    workflow.add_conditional_edges(
        "check_synthesis_threshold",
        route_after_threshold_check,
        {
            "collect_pending_events": "collect_pending_events",
            "skip_synthesis": END,
        },
    )

    # Linear flow after threshold passed
    workflow.add_edge("collect_pending_events", "synthesize_memory")
    workflow.add_edge("synthesize_memory", "persist_memory")
    workflow.add_edge("persist_memory", END)

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
# Use get_memory_synthesis_graph() instead of direct import
_memory_synthesis_graph = None
# Lock is event-loop-scoped — only valid when all callers share the same loop.
# Currently safe: graph singletons are only accessed from the main event loop
# (memory/knowledge synthesis schedulers), never from Dreamer's deep sleep thread.
_memory_graph_lock = asyncio.Lock()


async def get_memory_synthesis_graph():
    """
    Get (or build) the memory synthesis graph singleton.

    Lazy initialization pattern for async context manager handling.
    Uses asyncio.Lock to prevent concurrent builds leaking connection pools.

    Usage in scheduler:
        graph = await get_memory_synthesis_graph()
        result = await graph.ainvoke(
            {"anima_id": anima_id},
            config={"configurable": {"thread_id": anima_id}}
        )
    """
    global _memory_synthesis_graph
    if _memory_synthesis_graph is not None:
        return _memory_synthesis_graph
    async with _memory_graph_lock:
        if _memory_synthesis_graph is None:
            _memory_synthesis_graph = await build_memory_synthesis_graph()
        return _memory_synthesis_graph
