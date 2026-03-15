"""
Tests for memory synthesis domain operation extensions.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from app.domain.memory_operations import MemoryOperations
from app.domain.event_operations import EventOperations
from app.domain.anima_operations import AnimaOperations
from app.models.database.animas import AnimaCreate
from app.models.database.events import EventCreate, EventType
from app.models.database.memories import MemoryCreate


def test_get_last_memory_time_with_memories(rls_session, test_user_context):
    """Test get_last_memory_time returns most recent memory timestamp."""
    db_session = rls_session
    # Create anima
    anima_data = AnimaCreate(name="Test Anima", description="Test")
    anima = AnimaOperations.create(db_session, anima_data, user_id=test_user_context["user_id"], organization_id=test_user_context["org_id"])

    # Create memories with different timestamps
    now = datetime.utcnow()
    mem1_data = MemoryCreate(
        anima_id=anima.id,
        summary="First memory",
        time_start=now - timedelta(hours=2)
    )
    mem2_data = MemoryCreate(
        anima_id=anima.id,
        summary="Second memory",
        time_start=now - timedelta(hours=1)
    )

    MemoryOperations.create(db_session, mem1_data)
    mem2 = MemoryOperations.create(db_session, mem2_data)
    db_session.commit()

    # Get last memory time
    last_time = MemoryOperations.get_last_memory_time(db_session, anima.id)

    # Should return created_at of most recent memory
    assert last_time is not None
    # Compare timestamps (handle timezone differences)
    mem2_created = mem2.created_at.replace(tzinfo=None) if mem2.created_at.tzinfo else mem2.created_at
    last_time_no_tz = last_time.replace(tzinfo=None) if last_time.tzinfo else last_time
    assert last_time_no_tz == mem2_created


def test_get_last_memory_time_no_memories(rls_session, test_user_context):
    """Test get_last_memory_time returns None when no memories exist."""
    db_session = rls_session
    anima_data = AnimaCreate(name="Test Anima", description="Test")
    anima = AnimaOperations.create(db_session, anima_data, user_id=test_user_context["user_id"], organization_id=test_user_context["org_id"])
    db_session.commit()

    last_time = MemoryOperations.get_last_memory_time(db_session, anima.id)
    assert last_time is None


def test_count_since(rls_session, test_user_context):
    """Test count_since returns correct event count."""
    db_session = rls_session
    # Create anima
    anima_data = AnimaCreate(name="Test Anima", description="Test")
    anima = AnimaOperations.create(db_session, anima_data, user_id=test_user_context["user_id"], organization_id=test_user_context["org_id"])

    # Create events at different times
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=1)

    # 2 events before cutoff
    for i in range(2):
        event_data = EventCreate(
            anima_id=anima.id,
            event_type=EventType.MESSAGE_IN,
            content=f"Old event {i}",
            occurred_at=cutoff - timedelta(minutes=30 + i)
        )
        EventOperations.create(db_session, event_data)

    # 3 events after cutoff
    for i in range(3):
        event_data = EventCreate(
            anima_id=anima.id,
            event_type=EventType.MESSAGE_IN,
            content=f"New event {i}",
            occurred_at=cutoff + timedelta(minutes=10 + i)
        )
        EventOperations.create(db_session, event_data)

    db_session.commit()

    # Count should only include events AFTER cutoff
    count = EventOperations.count_since(db_session, anima.id, cutoff)
    assert count == 3


def test_get_since_chronological_order(rls_session, test_user_context):
    """Test get_since returns events in chronological order."""
    db_session = rls_session
    anima_data = AnimaCreate(name="Test Anima", description="Test")
    anima = AnimaOperations.create(db_session, anima_data, user_id=test_user_context["user_id"], organization_id=test_user_context["org_id"])

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=1)

    # Create events in random order
    timestamps = [
        cutoff + timedelta(minutes=30),
        cutoff + timedelta(minutes=10),
        cutoff + timedelta(minutes=20),
    ]

    for i, ts in enumerate(timestamps):
        event_data = EventCreate(
            anima_id=anima.id,
            event_type=EventType.MESSAGE_IN,
            content=f"Event {i}",
            occurred_at=ts
        )
        EventOperations.create(db_session, event_data)

    db_session.commit()

    # Retrieve and check order
    events = EventOperations.get_since(db_session, anima.id, cutoff)

    assert len(events) == 3
    # Should be ordered: 10min, 20min, 30min
    assert events[0].occurred_at == cutoff + timedelta(minutes=10)
    assert events[1].occurred_at == cutoff + timedelta(minutes=20)
    assert events[2].occurred_at == cutoff + timedelta(minutes=30)
