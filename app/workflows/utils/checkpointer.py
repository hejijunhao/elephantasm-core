"""Shared PostgreSQL checkpointer setup for LangGraph workflows.

Two-phase connection strategy:
  Phase 1 (Setup): Direct connection for DDL (CREATE TABLE).
  Phase 2 (Runtime): pgBouncer-pooled connection for checkpoint CRUD.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings


async def configure_conn(conn):
    """Configure connection — disable prepared statements and run DISCARD ALL."""
    conn.prepare_threshold = None

    original_autocommit = conn.autocommit
    await conn.set_autocommit(True)
    try:
        async with conn.cursor() as cur:
            await cur.execute("DISCARD ALL")
    finally:
        await conn.set_autocommit(original_autocommit)


async def create_checkpointer() -> AsyncPostgresSaver:
    """
    Create a pgBouncer-compatible AsyncPostgresSaver.

    Phase 1: Setup tables via direct connection (MIGRATION_DATABASE_URL, port 5432).
    Phase 2: Return runtime checkpointer via pooled connection (DATABASE_URL, port 6543).

    Tables live in the `langgraph` schema (role's default search_path).
    """
    # Phase 1: Setup — DDL via direct connection
    async with AsyncPostgresSaver.from_conn_string(settings.MIGRATION_DATABASE_URL) as setup:
        await setup.setup()

    # Phase 2: Runtime — pooled connection for checkpoint CRUD
    runtime_pool = AsyncConnectionPool(
        settings.get_database_url_for_async(),
        min_size=1,
        max_size=10,
        configure=configure_conn,
        check=AsyncConnectionPool.check_connection,
        max_lifetime=300,
        open=False,
    )
    await runtime_pool.open()

    return AsyncPostgresSaver(conn=runtime_pool)
