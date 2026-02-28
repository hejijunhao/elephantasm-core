"""
Tests for Zero-Events Synthesis Fix

Verifies that synthesis is properly skipped when no events exist,
regardless of time-based accumulation score.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import text

from app.workflows.memory_synthesis.nodes.threshold_gate import (
    check_synthesis_threshold_node,
)
from app.workflows.memory_synthesis.state import MemorySynthesisState
from app.models.database.animas import Anima
from app.models.database.synthesis_config import SynthesisConfig
from app.domain.synthesis_config_operations import SynthesisConfigOperations
from app.core.database import get_db_session


@pytest.fixture
def anima(test_user_context):
    """Create test anima with RLS context."""
    with get_db_session() as session:
        user_id = str(test_user_context["user_id"])
        session.execute(
            text("SELECT set_config('app.current_user', :uid, false)"),
            {"uid": user_id},
        )

        anima = Anima(
            name="Test Anima",
            description="Test anima for zero-events testing",
            user_id=test_user_context["user_id"],
            organization_id=test_user_context["org_id"],
        )
        session.add(anima)
        session.flush()
        session.refresh(anima)
        anima_id = anima.id

        # Create synthesis config with known threshold
        config = SynthesisConfig(
            anima_id=anima_id,
            threshold=10.0,
            time_weight=1.0,
            event_weight=0.5,
            token_weight=0.0003,
        )
        session.add(config)
        session.commit()

        yield anima

        # Cleanup
        session.delete(config)
        session.delete(anima)
        session.commit()


class TestZeroEventsThresholdCheck:
    """Test threshold check behavior with zero events."""

    def test_zero_events_high_time_score(self, anima):
        """
        Zero events with high time score should skip synthesis.

        Scenario: Anima with no events, 15 hours since creation
        Expected: synthesis_triggered=False, skip_reason="no_events"
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 15.0,  # High score from time alone
            "time_factor": 15.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            "event_count": 0,  # No events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"

    def test_zero_events_below_threshold(self, anima):
        """
        Zero events below threshold should also skip.

        Scenario: Anima with no events, 2 hours since creation
        Expected: synthesis_triggered=False, skip_reason="no_events"
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 2.0,  # Below threshold (10.0)
            "time_factor": 2.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            "event_count": 0,  # No events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"

    def test_one_event_above_threshold(self, anima):
        """
        One event above threshold should proceed to synthesis.

        Scenario: Anima with 1 event, score > threshold
        Expected: synthesis_triggered=True, skip_reason=None
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 12.0,  # Above threshold (10.0)
            "time_factor": 10.0,
            "event_factor": 2.0,  # 1 event × 0.5 weight = 0.5 contribution
            "token_factor": 0.0,
            "event_count": 1,  # Has events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is True
        assert result["skip_reason"] is None

    def test_many_events_below_threshold(self, anima):
        """
        Many events below threshold should skip with different reason.

        Scenario: Anima with 5 events, score < threshold
        Expected: synthesis_triggered=False, skip_reason="below_threshold"
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 5.0,  # Below threshold (10.0)
            "time_factor": 2.0,
            "event_factor": 3.0,  # 5 events × 0.5 weight = 2.5 contribution
            "token_factor": 0.0,
            "event_count": 5,  # Has events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "below_threshold"

    def test_many_events_above_threshold(self, anima):
        """
        Many events above threshold should proceed to synthesis.

        Scenario: Anima with 10 events, score > threshold
        Expected: synthesis_triggered=True, skip_reason=None
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 15.0,  # Above threshold (10.0)
            "time_factor": 5.0,
            "event_factor": 10.0,  # 10 events × 0.5 weight = 5.0 contribution
            "token_factor": 0.0,
            "event_count": 10,  # Has many events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is True
        assert result["skip_reason"] is None

    def test_exactly_at_threshold_with_events(self, anima):
        """
        Score exactly at threshold with events should proceed.

        Scenario: Anima with score = 10.0 (exactly at threshold)
        Expected: synthesis_triggered=True (>= threshold)
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 10.0,  # Exactly at threshold
            "time_factor": 8.0,
            "event_factor": 2.0,
            "token_factor": 0.0,
            "event_count": 4,  # Has events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is True
        assert result["skip_reason"] is None

    def test_exactly_at_threshold_no_events(self, anima):
        """
        Score exactly at threshold but no events should skip.

        Scenario: Anima with score = 10.0 but event_count = 0
        Expected: synthesis_triggered=False, skip_reason="no_events"
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 10.0,  # Exactly at threshold
            "time_factor": 10.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            "event_count": 0,  # No events
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"

    def test_very_high_score_no_events(self, anima):
        """
        Very high score from time alone should still skip.

        Scenario: Anima inactive for 30 days (720 hours)
        Expected: synthesis_triggered=False, skip_reason="no_events"
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 720.0,  # 30 days of time accumulation
            "time_factor": 720.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            "event_count": 0,  # No events despite long time
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"


class TestThresholdCheckEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_missing_event_count_defaults_to_zero(self, anima):
        """
        Missing event_count in state should default to 0.

        Edge case: Older state schema without event_count field
        Expected: Treated as 0 events, skipped
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 15.0,
            "time_factor": 15.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            # event_count deliberately omitted
        }

        result = check_synthesis_threshold_node(state)

        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"

    def test_negative_event_count_treated_as_zero(self, anima):
        """
        Negative event_count (invalid data) should skip.

        Edge case: Database corruption or invalid state
        Expected: Treated as no events
        """
        state: MemorySynthesisState = {
            "anima_id": str(anima.id),
            "accumulation_score": 15.0,
            "time_factor": 15.0,
            "event_factor": 0.0,
            "token_factor": 0.0,
            "event_count": -5,  # Invalid negative count
        }

        result = check_synthesis_threshold_node(state)

        # Threshold gate uses `event_count <= 0`, so -5 is treated as no events
        assert result["synthesis_triggered"] is False
        assert result["skip_reason"] == "no_events"

    def test_custom_anima_threshold(self, test_user_context):
        """
        Test with anima having custom threshold (not default 10.0).

        Ensures threshold is read from DB config correctly.
        """
        with get_db_session() as session:
            user_id = str(test_user_context["user_id"])
            session.execute(
                text("SELECT set_config('app.current_user', :uid, false)"),
                {"uid": user_id},
            )

            anima = Anima(
                name="Custom Threshold Anima",
                user_id=test_user_context["user_id"],
                organization_id=test_user_context["org_id"],
            )
            session.add(anima)
            session.flush()

            config = SynthesisConfig(
                anima_id=anima.id,
                threshold=50.0,  # Custom high threshold
                time_weight=1.0,
                event_weight=0.5,
                token_weight=0.0003,
            )
            session.add(config)
            session.commit()

            try:
                # Score above default (10.0) but below custom (50.0)
                state: MemorySynthesisState = {
                    "anima_id": str(anima.id),
                    "accumulation_score": 30.0,
                    "time_factor": 20.0,
                    "event_factor": 10.0,
                    "token_factor": 0.0,
                    "event_count": 20,
                }

                result = check_synthesis_threshold_node(state)

                # Should not trigger (30.0 < 50.0)
                assert result["synthesis_triggered"] is False
                assert result["skip_reason"] == "below_threshold"

            finally:
                session.delete(config)
                session.delete(anima)
                session.commit()
