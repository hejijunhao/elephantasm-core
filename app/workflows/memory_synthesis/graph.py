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
    # Schema: langgraph (dedicated schema, see migration 54548631fcaa)
    # Tables: checkpoints, checkpoint_writes, checkpoint_blobs (managed by LangGraph)
    # Note: postgres role has search_path = langgraph, public, extensions
    #       This means both setup and runtime connections automatically find langgraph schema
    #       No session-level search_path configuration needed (role-level default works)

    async with AsyncPostgresSaver.from_conn_string(settings.MIGRATION_DATABASE_URL) as setup_checkpointer:
        # Create checkpoint tables if they don't exist (idempotent)
        # Tables created in langgraph schema (via role's default search_path)
        # Tables managed by LangGraph library (not Alembic)
        await setup_checkpointer.setup()

    # Context manager exits, direct connection closed

    # Phase 2: Runtime - Checkpoint CRUD (Pooled Connection)
    # -------------------------------------------------------
    # Uses DATABASE_URL (port 6543, pgBouncer transaction pooling)
    # All checkpoint read/write operations during workflow execution use pooling
    # Checkpoint operations (.put/.get/.list) are simple INSERT/SELECT queries
    # Compatible with pgBouncer transaction mode when prepared statements are disabled
    #
    # Note: We manually enter the async context manager and keep it alive
    # The checkpointer connection stays open for the application lifetime
    # pgBouncer handles connection pooling underneath
    # Tables were already created in langgraph schema during setup phase (line 124)
    #
    # Why this works:
    # - Setup (DDL) already completed via direct connection in langgraph schema
    # - Runtime only does INSERT/SELECT/UPDATE (transactional operations)
    # - No session-level parameters needed (role's default search_path finds langgraph schema)
    # - Prepared statements DISABLED (prepare_threshold=None) via custom pool configure hook
    # - No temp tables, search_path changes, or other session-level features needed

    # Get database URL and create async checkpointer with pgBouncer optimizations
    # CRITICAL: We need to disable prepared statements for pgBouncer compatibility
    # AsyncPostgresSaver uses psycopg async internally, which also creates prepared statements
    #
    # Solution: Use AsyncPostgresSaver.from_conn_string() but configure connections properly
    # The configure hook needs to handle async context correctly
    from psycopg_pool import AsyncConnectionPool

    runtime_url = settings.get_database_url_for_async()

    # Create async connection pool with prepare_threshold=None
    # Configure hook runs on every connection created by the pool
    async def configure_conn(conn):
        """Configure connection - disable prepared statements and run DISCARD ALL."""
        # Set prepare_threshold to completely disable prepared statements
        conn.prepare_threshold = None

        # Execute DISCARD ALL to clear recycled pgBouncer connection state
        # DISCARD ALL requires autocommit mode (cannot run in transaction)
        original_autocommit = conn.autocommit
        await conn.set_autocommit(True)

        try:
            async with conn.cursor() as cur:
                await cur.execute("DISCARD ALL")
        finally:
            # Restore original autocommit mode
            await conn.set_autocommit(original_autocommit)

    # Create async pool with custom configuration
    # Important: Don't open in constructor (deprecated), use context manager
    runtime_pool = AsyncConnectionPool(
        runtime_url,
        min_size=1,
        max_size=10,
        configure=configure_conn,
        check=AsyncConnectionPool.check_connection,  # Validate before use (fixes pgBouncer idle drops)
        max_lifetime=300,  # Refresh connections every 5min (before pgBouncer idle timeout)
        open=False,  # Don't auto-open (will open explicitly)
    )

    # Open the pool explicitly (proper async pattern)
    await runtime_pool.open()

    # Create checkpointer with custom pool
    runtime_checkpointer = AsyncPostgresSaver(conn=runtime_pool)

    # Note: NO setup() call here - tables already created in Phase 1
    # Calling setup() again would fail with pgBouncer (DDL not supported in transaction mode)

    # Compile graph with persistent checkpointer for all runtime operations
    # Note: We intentionally never call __aexit__() to keep connection alive
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
