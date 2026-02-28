"""Alembic environment configuration for synchronous migrations (OSS version)."""

from logging.config import fileConfig

from sqlalchemy import pool, create_engine
from sqlalchemy.engine import Connection

from alembic import context

# Import settings
from app.core.config import settings

# Import all models for autogenerate (OSS subset)
from app.models.database.user import User
from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.memories_events import MemoryEvent
from app.models.database.synthesis_config import SynthesisConfig
from app.models.database.knowledge import Knowledge
from app.models.database.knowledge_audit_log import KnowledgeAuditLog
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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (synchronous)."""
    database_url = settings.MIGRATION_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={
            "options": "-c search_path=public"
        }
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
