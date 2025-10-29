"""
Memory Synthesis Workflow Graph

Assembles nodes into LangGraph StateGraph with PostgreSQL checkpointing.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .state import MemorySynthesisState
from .nodes import (
    calculate_accumulation_score_node,
    check_synthesis_threshold_node,
    route_after_threshold_check,
    collect_pending_events_node,
    synthesize_memory_node,
    persist_memory_node,
)
from app.core.config import settings


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

    # Phase 1: Setup - Create Tables (Direct Connection)
    # ---------------------------------------------------
    # Uses MIGRATION_DATABASE_URL (port 5432, direct to Postgres)
    # Required for DDL operations (CREATE TABLE) which pgBouncer doesn't support
    # Schema: langgraph (separated from application domain models in public)
    # Permissions: Granted via Alembic migration 54548631fcaa
    # Note: options parameter works with direct Postgres connection

    setup_conn = f"{settings.MIGRATION_DATABASE_URL}?options=-c%20search_path%3Dlanggraph%2Cpublic"

    async with AsyncPostgresSaver.from_conn_string(setup_conn) as setup_checkpointer:
        # Create checkpoint tables if they don't exist (idempotent)
        # Tables managed by LangGraph library (not Alembic)
        await setup_checkpointer.setup()

    # Context manager exits, direct connection closed

    # Phase 2: Runtime - Checkpoint CRUD (Pooled Connection)
    # -------------------------------------------------------
    # Uses DATABASE_URL (port 6543, pgBouncer transaction pooling)
    # All checkpoint read/write operations during workflow execution use pooling
    # Checkpoint operations (.put/.get/.list) are simple INSERT/SELECT queries
    # Compatible with pgBouncer transaction mode (no prepared statements needed)
    #
    # Note: We use same connection string format as setup phase
    # pgBouncer in transaction mode supports most SQL operations except:
    # - DDL (CREATE TABLE) - handled in setup phase
    # - Prepared statements - AsyncPostgresSaver doesn't use these
    # - Session variables - handled via search_path in connection string
    #
    # Problem: pgBouncer rejects 'options' parameter
    # Solution: Use DATABASE_URL directly - checkpointer will use default schema
    # The tables were created in 'langgraph' schema, but AsyncPostgresSaver
    # internally handles schema-qualified queries when needed

    async with AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL) as runtime_checkpointer:
        # Tables already exist in langgraph schema from setup phase
        # Compile graph with pooled checkpointer for all runtime operations
        graph = workflow.compile(checkpointer=runtime_checkpointer)

        return graph


# ============================================================================
# Singleton Instance
# ============================================================================

# Note: Graph initialization moved to lazy loading due to async context manager
# Use get_memory_synthesis_graph() instead of direct import
_memory_synthesis_graph = None

async def get_memory_synthesis_graph():
    """
    Get (or build) the memory synthesis graph singleton.

    Lazy initialization pattern for async context manager handling.

    Usage in scheduler:
        graph = await get_memory_synthesis_graph()
        result = await graph.ainvoke(
            {"anima_id": anima_id},
            config={"configurable": {"thread_id": anima_id}}
        )
    """
    global _memory_synthesis_graph
    if _memory_synthesis_graph is None:
        _memory_synthesis_graph = await build_memory_synthesis_graph()
    return _memory_synthesis_graph
