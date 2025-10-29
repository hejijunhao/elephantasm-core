"""Alembic environment configuration for async migrations."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Import settings
from app.core.config import settings

# Import all models for autogenerate
from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.user import User
from app.models.database.memories import Memory
from app.models.database.memories_events import MemoryEvent
from app.models.database.mixins.timestamp import TimestampMixin

# Import SQLModel's metadata
from sqlmodel import SQLModel

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # Use direct connection URL for offline mode (no async driver needed)
    url = settings.MIGRATION_DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode (async)."""
    # Use direct connection (port 5432) for migrations - supports all PostgreSQL features
    # Transform plain postgresql:// URL to async psycopg driver format
    database_url = settings.MIGRATION_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

    # Create engine for migrations (no prepare_threshold needed with direct connection)
    connectable = create_async_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
