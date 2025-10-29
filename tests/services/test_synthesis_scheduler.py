"""
Tests for Memory Synthesis Scheduler (Refactored Architecture)
"""
import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.services.scheduler import (
    get_scheduler_orchestrator,
    get_memory_synthesis_scheduler,
    MemorySynthesisScheduler,
    SchedulerOrchestrator,
    SchedulerBase,
)


class TestSchedulerOrchestrator:
    """Test suite for SchedulerOrchestrator."""

    def test_scheduler_orchestrator_instance(self):
        """Test get_scheduler_orchestrator returns same instance."""
        scheduler1 = get_scheduler_orchestrator()
        scheduler2 = get_scheduler_orchestrator()

        assert scheduler1 is scheduler2
        assert isinstance(scheduler1, SchedulerOrchestrator)

    def test_scheduler_initialization(self):
        """Test scheduler initializes in stopped state."""
        scheduler = get_scheduler_orchestrator()
        status = scheduler.get_status()

        assert status["running"] is False
        assert status["total_jobs"] >= 0  # May have jobs from main.py

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self):
        """Test scheduler can start and stop gracefully."""
        scheduler = get_scheduler_orchestrator()

        # Start scheduler
        await scheduler.start()
        status = scheduler.get_status()
        assert status["running"] is True

        # Stop scheduler
        await scheduler.stop()
        status = scheduler.get_status()
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_scheduler_double_start_ignored(self):
        """Test starting already-running scheduler is idempotent."""
        scheduler = get_scheduler_orchestrator()

        await scheduler.start()
        status1 = scheduler.get_status()

        # Second start should be no-op
        await scheduler.start()
        status2 = scheduler.get_status()

        assert status1["running"] == status2["running"] == True

        await scheduler.stop()


class TestSynthesisWorkflow:
    """Test suite for MemorySynthesisScheduler."""

    def test_synthesis_scheduler_singleton(self):
        """Test get_memory_synthesis_scheduler returns same instance."""
        scheduler1 = get_memory_synthesis_scheduler()
        scheduler2 = get_memory_synthesis_scheduler()

        assert scheduler1 is scheduler2
        assert isinstance(scheduler1, MemorySynthesisScheduler)

    def test_scheduler_properties(self):
        """Test scheduler has correct properties."""
        scheduler = get_memory_synthesis_scheduler()

        assert scheduler.scheduler_name == "memory_synthesis"
        assert scheduler.job_interval_hours > 0
        assert isinstance(scheduler.job_interval_hours, int)

    def test_initial_status(self):
        """Test get_status returns correct initial state."""
        scheduler = get_memory_synthesis_scheduler()
        status = scheduler.get_status()

        assert status["scheduler"] == "memory_synthesis"
        assert status["interval_hours"] > 0
        assert status["last_run"] is None
        assert status["stats"]["total_runs"] == 0
        assert status["stats"]["successful_runs"] == 0
        assert status["stats"]["failed_runs"] == 0

    @pytest.mark.asyncio
    async def test_scheduler_registration(self):
        """Test scheduler can register with scheduler."""
        scheduler = get_scheduler_orchestrator()
        scheduler = get_memory_synthesis_scheduler()

        # Register scheduler
        await scheduler.register()

        # Check job exists
        job = scheduler.get_job("memory_synthesis_job")
        assert job is not None
        assert job.id == "memory_synthesis_job"

    @pytest.mark.asyncio
    async def test_scheduler_status_after_registration(self):
        """Test scheduler status shows running after registration and start."""
        scheduler = get_scheduler_orchestrator()
        scheduler = get_memory_synthesis_scheduler()

        # Register and start
        await scheduler.register()
        await scheduler.start()

        # Check status
        status = scheduler.get_status()
        assert status["running"] is True
        assert status["next_run"] is not None

        await scheduler.stop()


class TestManualSynthesisTrigger:
    """Test suite for manual synthesis triggers."""

    @pytest.mark.asyncio
    async def test_trigger_synthesis_single_anima_not_found(self):
        """Test manual trigger for non-existent anima."""
        scheduler = get_memory_synthesis_scheduler()
        fake_anima_id = uuid4()

        # This should fail gracefully (anima not found in DB)
        result = await scheduler.execute_for_anima(fake_anima_id)

        assert result["anima_id"] == str(fake_anima_id)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_trigger_synthesis_all_animas(self):
        """Test manual trigger for all animas."""
        scheduler = get_memory_synthesis_scheduler()

        # Trigger for all animas (will process whatever exists in DB)
        result = await scheduler.trigger_manual(anima_id=None)

        # Should have run for whatever animas exist in DB
        assert "total_animas" in result
        assert "successful" in result
        assert "failed" in result
        assert "skipped" in result
        assert "items_created" in result

        # Total should equal sum of outcomes
        total = result["successful"] + result["failed"] + result["skipped"]
        assert result["total_animas"] == total

    @pytest.mark.asyncio
    async def test_trigger_manual_single_anima(self):
        """Test manual trigger wrapper for single anima."""
        scheduler = get_memory_synthesis_scheduler()
        fake_anima_id = uuid4()

        # Trigger single anima
        result = await scheduler.trigger_manual(anima_id=fake_anima_id)

        # Should call execute_for_anima
        assert "anima_id" in result
        assert result["anima_id"] == str(fake_anima_id)


class TestSchedulerStatistics:
    """Test suite for scheduler statistics tracking."""

    def test_initial_stats(self):
        """Test initial statistics are zeroed."""
        scheduler = get_memory_synthesis_scheduler()
        status = scheduler.get_status()
        stats = status["stats"]

        assert stats["total_runs"] == 0
        assert stats["successful_runs"] == 0
        assert stats["failed_runs"] == 0
        assert stats["animas_processed"] == 0
        assert stats["items_created"] == 0

    @pytest.mark.asyncio
    async def test_stats_updated_after_manual_run(self):
        """Test statistics update after synthesis run."""
        scheduler = get_memory_synthesis_scheduler()

        # Trigger synthesis (will process zero animas in test DB)
        await scheduler.trigger_manual(anima_id=None)

        # Check stats updated
        status = scheduler.get_status()
        stats = status["stats"]

        # Manual trigger of all animas increments total_runs
        assert stats["total_runs"] > 0


# Integration test (requires database)
@pytest.mark.skip(reason="Integration test - requires database with test data")
class TestSchedulerIntegration:
    """Integration tests for scheduler (requires database)."""

    @pytest.mark.asyncio
    async def test_scheduled_synthesis_with_real_anima(self):
        """Test scheduled synthesis with real anima and events."""
        # TODO: Create test anima with events
        # TODO: Trigger synthesis
        # TODO: Verify memory created
        # TODO: Verify provenance links created
        pass

    @pytest.mark.asyncio
    async def test_concurrent_synthesis(self):
        """Test concurrent synthesis for multiple animas."""
        # TODO: Create 10 test animas with events
        # TODO: Trigger synthesis for all
        # TODO: Verify all processed concurrently
        # TODO: Verify no database deadlocks
        pass
