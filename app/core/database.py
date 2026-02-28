"""
Database connection and session management.

Uses synchronous SQLAlchemy with NullPool pattern.
Connection pooling delegated to pgBouncer at infrastructure level.
"""

import os
from typing import Generator, Optional
from contextlib import contextmanager
from urllib.parse import urlparse
from uuid import UUID
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, event
import logging
import psycopg

from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')


# Get database URL from settings and ensure it uses psycopg3 driver
DATABASE_URL = settings.DATABASE_URL

if not DATABASE_URL:
    raise ValueError("DATABASE_URL could not be constructed from settings")

# Ensure URL specifies psycopg driver (psycopg3)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise ValueError("DATABASE_URL must start with postgresql:// or postgresql+psycopg://")

# Parse database URL for logging (don't log password!)
db_url = urlparse(DATABASE_URL)
logger.info("\n===== DATABASE CONNECTION INFO =====\n")
logger.info(f"Database driver: postgresql+psycopg (custom creator)")
logger.info(f"Database host: {db_url.hostname}")
logger.info(f"Database port: {db_url.port}")
logger.info(f"Database name: {db_url.path[1:]}")  # Remove leading slash


# Create engine WITHOUT custom creator, using connect_args instead
# This is simpler and may work better with psycopg3's prepare_threshold
logger.info("Configuring database engine with NullPool (pgBouncer handles pooling):")
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,       # Let pgBouncer handle all pooling
    connect_args={
        "prepare_threshold": None,  # CRITICAL: Set to None to completely disable prepared statements
        "autocommit": False,
    },
    pool_pre_ping=True,
    echo=False
)

# Apply execution options to disable SQLAlchemy's prepared statement cache
# CRITICAL: Must assign back to engine variable for options to take effect
engine = engine.execution_options(
    # Disable SQLAlchemy's prepared statement cache (critical for pgBouncer)
    # This prevents "DuplicatePreparedStatement" errors when connections are recycled
    postgresql_prepared_statement_cache_size=0
)

# Event listener: Reset session state on every connection
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):  # noqa: ARG001
    """
    Reset session state on every connection from pgBouncer.

    Executes DISCARD ALL to clear any prepared statements or session state
    from the recycled connection. This is CRITICAL for pgBouncer compatibility.
    """
    # Execute DISCARD ALL without changing connection state
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("DISCARD ALL")
        dbapi_conn.commit()
        cursor.close()
    except Exception:
        try:
            dbapi_conn.rollback()
        except Exception:
            pass

logger.info("Database engine configured with:")
logger.info(f"  - Pooling: NullPool (delegated to pgBouncer)")
logger.info(f"  - Connection parameters:")
logger.info(f"    • prepare_threshold: None (completely disables prepared statements)")
logger.info(f"    • autocommit: False (transaction mode)")
logger.info(f"    • DISCARD ALL on connect (event listener clears recycled state)")
logger.info(f"  - Health checks: Enabled (pool_pre_ping=True)")
logger.info(f"  - SQLAlchemy statement cache: 0 (via execution_options)")

# Create sessionmaker with expire_on_commit=False to prevent automatic refresh after commit
# This is critical for RLS context management
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,  # Prevents automatic refresh after commit
    autoflush=False,         # Explicit control over when to flush
    autocommit=False         # Use transactions explicitly
)

logger.info("SessionLocal configured with:")
logger.info(f"  - expire_on_commit: False (prevents post-commit refresh)")
logger.info(f"  - autoflush: False (explicit control)")
logger.info(f"  - autocommit: False (explicit transactions)")


def verify_migrations() -> None:
    # Verify that database migrations have been applied.
    logger.info("Verifying database migrations...")
    try:
        with Session(engine) as session:
            # Check if alembic_version table exists
            result = session.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'alembic_version'
                )
            """))
            alembic_table_exists = result.scalar()

            if not alembic_table_exists:
                logger.error("❌ Alembic version table not found!")
                logger.error("   Run 'alembic upgrade head' to initialize the database schema.")
                raise RuntimeError(
                    "Database schema not initialized. "
                    "Please run 'alembic upgrade head' before starting the application."
                )

            # Get current migration version
            result = session.execute(text("SELECT version_num FROM alembic_version"))
            current_version = result.scalar()

            if current_version:
                logger.info(f"✅ Database migrations verified (current: {current_version})")
            else:
                logger.warning("⚠️  No migration version found in alembic_version table")

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Failed to verify migrations: {e}")
        logger.error("Ensure the database is accessible and migrations have been applied.")
        raise


def get_db() -> Generator[Session, None, None]:
    # Get database session from the connection pool.
    # Uses SessionLocal with expire_on_commit=False for RLS compatibility.
    db = SessionLocal()
    try:
        yield db
        # Commit the transaction if no exceptions occurred
        db.commit()
    except Exception:
        # Rollback on any exception
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_with_rls_context(user_id: Optional[UUID]) -> Generator[Session, None, None]:
    """
    Internal: Database session with RLS context for given user_id.

    ⚠️ CRITICAL: Sets session variable for RLS policies!
    - user_id → app.current_user session variable
    - Transaction-scoped (SET LOCAL) - auto-resets when transaction ends
    - RLS policies filter all queries by user_id

    Args:
        user_id: Current user ID (None for unauthenticated)

    Yields:
        Session with RLS context set
    """
    db = SessionLocal()
    try:
        # Set RLS context if user authenticated
        if user_id is not None:
            # Note: We quote "app.current_user" because current_user is a PostgreSQL reserved keyword
            # SET LOCAL doesn't support parameterized queries in PostgreSQL
            # UUID type validation (hex + hyphens only) prevents SQL injection
            user_id_str = str(user_id)
            # Defense-in-depth: verify UUID format before interpolation
            if not all(c in '0123456789abcdef-' for c in user_id_str.lower()):
                raise ValueError(f"Invalid UUID format: {user_id_str}")
            db.execute(text(f"SET LOCAL \"app.current_user\" = '{user_id_str}'"))

        yield db
        # Commit the transaction if no exceptions occurred
        db.commit()  # ⚠️ Clears session variables in pgBouncer!
    except Exception:
        # Rollback on any exception
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions in non-FastAPI contexts.
    Used by LangGraph nodes (sync operations in thread pool).
    Auto-commits on success, auto-rolls back on exception.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()  # Auto-commit on success
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Test database connection on module import
logger.info("Testing initial database connection...")
try:
    with Session(engine) as session:
        session.execute(text("SELECT 1"))
        logger.info("Initial database connection test successful!")
except Exception as e:
    logger.error(f"Failed to connect to database: {e}")
    raise

def get_background_session() -> Session:
    """
    Create a standalone session for background tasks.

    Unlike get_db() which is a generator for FastAPI dependency injection,
    this returns a plain Session for use in fire-and-forget background tasks.

    IMPORTANT: Caller is responsible for commit/rollback/close.
    Uses same engine with NullPool + pgBouncer transaction pooling.

    Example:
        session = get_background_session()
        try:
            # do work
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    """
    return SessionLocal()


# Verify migrations have been applied (does NOT create tables)
verify_migrations()
