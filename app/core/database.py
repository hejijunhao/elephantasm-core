"""
Database connection and session management.

Uses synchronous SQLAlchemy with NullPool pattern.
Connection pooling delegated to pgBouncer at infrastructure level.

Pattern: Marlin Shipbroking Platform Architecture
"""

import os
from typing import Generator
from contextlib import contextmanager
from urllib.parse import urlparse
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import logging

from app.core.config import settings

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')


# Get database URL from settings
DATABASE_URL = settings.DATABASE_URL
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Transform plain postgresql:// URL to psycopg driver format (sync psycopg3)
# Note: Using +psycopg (not +psycopg_async) for synchronous connections
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

# Parse database URL for logging (don't log password!)
db_url = urlparse(DATABASE_URL)
logger.info("\n===== DATABASE CONNECTION INFO =====\n")
logger.info(f"Database driver: postgresql")
logger.info(f"Database host: {db_url.hostname}")
logger.info(f"Database port: {db_url.port}")
logger.info(f"Database name: {db_url.path[1:]}")  # Remove leading slash

# Create engine with NullPool to avoid double-pooling with pgBouncer
# Since Supabase already provides connection pooling via pgBouncer,
# we don't need SQLAlchemy's pool on top
logger.info("Configuring database engine with NullPool (pgBouncer handles pooling):")
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,      # Let pgBouncer handle all pooling
    pool_pre_ping=True,      # Still verify connections before use
    echo=False                # Set to True to log SQL queries
)

logger.info("Database engine configured with:")
logger.info(f"  - Pooling: NullPool (delegated to pgBouncer)")
logger.info(f"  - Health checks: Enabled (pool_pre_ping=True)")

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
    """
    Verify that database migrations have been applied.

    Checks for the existence of the alembic_version table.
    Does NOT create tables - schema must be managed via Alembic migrations.

    Raises:
        RuntimeError: If alembic_version table doesn't exist (migrations not applied)
    """
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
    """
    Get database session from the connection pool.
    Uses SessionLocal with expire_on_commit=False for RLS compatibility.

    Usage in FastAPI routes:
        @router.get("/spirits")
        async def get_spirits(db: Session = Depends(get_db)):
            # FastAPI runs sync code in thread pool automatically
            spirits = SpiritOperations.list(db)  # No await!
            return spirits

    Yields:
        Session: Database session from the pool
    """
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
def get_session_context():
    """
    Context manager for database sessions outside FastAPI.

    Usage in scripts/workflows:
        from app.core.database import get_session_context

        with get_session_context() as db:
            spirit = SpiritOperations.create(db, data)
            db.commit()

    Yields:
        Session: Database session
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions in non-FastAPI contexts.

    Used by LangGraph nodes (sync operations in thread pool).
    Auto-commits on success, auto-rolls back on exception.

    Usage in workflow nodes:
        from app.core.database import get_db_session

        with get_db_session() as session:
            memory = MemoryOperations.create(session, data)
            # Auto-commits on context exit

    Yields:
        Session: Database session
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

# Verify migrations have been applied (does NOT create tables)
verify_migrations()
