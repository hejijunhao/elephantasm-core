"""Tests for threshold reset behavior when skipping synthesis due to zero events.

Verifies that last_synthesis_check_at prevents infinite time accumulation.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.models.database.animas import Anima, AnimaCreate
from app.models.database.synthesis_config import SynthesisConfig
from app.domain.anima_operations import AnimaOperations
from app.domain.synthesis_config_operations import SynthesisConfigOperations
from app.domain.synthesis_metrics import compute_accumulation_score


def test_baseline_uses_last_synthesis_check_at_when_most_recent(rls_session, test_user_context):
    """Baseline should use last_synthesis_check_at if more recent than last memory."""
    db_session = rls_session
    # Create anima 3 days ago
    anima = Anima(
        id=uuid4(),
        name="Test Anima",
        user_id=test_user_context["user_id"],
        organization_id=test_user_context["org_id"],
        created_at=datetime.now(timezone.utc) - timedelta(days=3)
    )
    db_session.add(anima)
    db_session.flush()

    # Get config (auto-created)
    config = SynthesisConfigOperations.get_or_create_default(db_session, anima.id)

    # Set last_synthesis_check_at to 1 hour ago (simulating recent skip)
    config.last_synthesis_check_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(config)
    db_session.commit()

    # Calculate accumulation score
    result = compute_accumulation_score(db_session, anima.id)

    # Hours since last should be ~1 hour, not 3 days
    assert 0.9 <= result["hours_since_last"] <= 1.1, \
        f"Expected ~1 hour, got {result['hours_since_last']:.2f}"

    # Time factor should be ~1.0 (1 hour × 1.0 weight)
    assert 0.9 <= result["time_factor"] <= 1.1, \
        f"Expected ~1.0, got {result['time_factor']:.2f}"


def test_baseline_prefers_last_memory_if_more_recent(rls_session, test_user_context):
    """Baseline should use last memory time if more recent than last_synthesis_check_at."""
    db_session = rls_session
    from app.models.database.memories import Memory, MemoryState

    # Create anima 3 days ago
    anima = Anima(
        id=uuid4(),
        name="Test Anima",
        user_id=test_user_context["user_id"],
        organization_id=test_user_context["org_id"],
        created_at=datetime.now(timezone.utc) - timedelta(days=3)
    )
    db_session.add(anima)
    db_session.flush()

    # Get config
    config = SynthesisConfigOperations.get_or_create_default(db_session, anima.id)

    # Set last_synthesis_check_at to 2 hours ago
    config.last_synthesis_check_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.add(config)
    db_session.commit()

    # Create memory 1 hour ago (more recent than check)
    memory = Memory(
        id=uuid4(),
        anima_id=anima.id,
        summary="Recent memory",
        state=MemoryState.ACTIVE,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    db_session.add(memory)
    db_session.commit()

    # Calculate accumulation score
    result = compute_accumulation_score(db_session, anima.id)

    # Hours since last should be ~1 hour (memory time), not 2 hours (check time)
    assert 0.9 <= result["hours_since_last"] <= 1.1, \
        f"Expected ~1 hour, got {result['hours_since_last']:.2f}"


def test_baseline_falls_back_to_anima_created_at(rls_session, test_user_context):
    """Baseline should use anima.created_at if no check or memory."""
    db_session = rls_session
    # Create anima 2 hours ago
    anima = Anima(
        id=uuid4(),
        name="Test Anima",
        user_id=test_user_context["user_id"],
        organization_id=test_user_context["org_id"],
        created_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    db_session.add(anima)
    db_session.commit()

    # Calculate accumulation score (no config.last_synthesis_check_at, no memories)
    result = compute_accumulation_score(db_session, anima.id)

    # Hours since last should be ~2 hours (anima creation)
    assert 1.9 <= result["hours_since_last"] <= 2.1, \
        f"Expected ~2 hours, got {result['hours_since_last']:.2f}"


def test_threshold_reset_prevents_infinite_accumulation(rls_session, test_user_context):
    """Simulates hourly checks with zero events, verifying time doesn't accumulate infinitely."""
    db_session = rls_session
    from app.workflows.memory_synthesis.nodes.threshold_gate import check_synthesis_threshold_node

    # Create anima 15 hours ago
    anima = Anima(
        id=uuid4(),
        name="Test Anima",
        user_id=test_user_context["user_id"],
        organization_id=test_user_context["org_id"],
        created_at=datetime.now(timezone.utc) - timedelta(hours=15)
    )
    db_session.add(anima)
    db_session.commit()

    # First check: 15 hours accumulated, 0 events → should skip
    state = {
        "anima_id": str(anima.id),
        "accumulation_score": 15.0,
        "time_factor": 15.0,
        "event_count": 0
    }
    result = check_synthesis_threshold_node(state)

    # Verify skip
    assert result["synthesis_triggered"] is False
    assert result["skip_reason"] == "no_events"

    # Verify timestamp was reset
    db_session.expire_all()  # Refresh from DB
    config = SynthesisConfigOperations.get_by_anima_id(db_session, anima.id)
    assert config.last_synthesis_check_at is not None

    # Handle timezone-naive timestamps from DB
    check_time = config.last_synthesis_check_at
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)

    assert (datetime.now(timezone.utc) - check_time).total_seconds() < 5

    # Second check: immediately after (simulating next hourly run)
    # Time factor should be ~0, not 15+1=16
    result2 = compute_accumulation_score(db_session, anima.id)
    assert result2["hours_since_last"] < 0.1, \
        f"Expected near-zero hours, got {result2['hours_since_last']:.2f}"
    assert result2["time_factor"] < 0.1, \
        f"Expected near-zero time factor, got {result2['time_factor']:.2f}"


def test_baseline_timezone_aware(rls_session, test_user_context):
    """Baseline timestamp should handle timezone-naive timestamps gracefully."""
    db_session = rls_session
    # Create anima with naive timestamp (simulating PostgreSQL quirk)
    # Use utcnow() to get naive UTC time (as DB would return)
    anima = Anima(
        id=uuid4(),
        name="Test Anima",
        user_id=test_user_context["user_id"],
        organization_id=test_user_context["org_id"],
        created_at=datetime.utcnow() - timedelta(hours=2)  # Naive UTC
    )
    db_session.add(anima)
    db_session.commit()

    # Should not raise exception
    result = compute_accumulation_score(db_session, anima.id)

    # Should still calculate correctly
    assert 1.9 <= result["hours_since_last"] <= 2.1
