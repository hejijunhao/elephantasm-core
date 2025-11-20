"""
Pytest configuration and fixtures for testing.
"""
import pytest
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy.pool import StaticPool
from app.core.database import SessionLocal

# Import all models to ensure SQLAlchemy relationships are configured
from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.memories_events import MemoryEvent
from app.models.database.user import User


@pytest.fixture(name="db_session", scope="function")
def db_session_fixture():
    """
    Provides a clean database session for each test.

    Uses the existing database engine from app.core.database.
    Creates a new session for each test and rolls back after completion.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()  # Rollback to ensure test isolation
        session.close()
