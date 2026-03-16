"""
Tests for PostgreSQL Advisory Lock Helper

Verifies cross-machine coordination via pg_try_advisory_lock().
"""

import pytest
from uuid import uuid4

from app.services.scheduler.advisory_lock import advisory_lock


class TestAdvisoryLockAcquisition:
    """Basic lock acquire/release behavior."""

    def test_lock_acquired_returns_true(self):
        """First acquisition should succeed."""
        with advisory_lock("test_lock_acquire") as acquired:
            assert acquired is True

    def test_lock_reacquirable_after_release(self):
        """Lock should be reusable after context manager exits."""
        with advisory_lock("test_lock_reacquire") as acquired:
            assert acquired is True

        with advisory_lock("test_lock_reacquire") as acquired:
            assert acquired is True

    def test_anima_lock_acquired_returns_true(self):
        """Per-anima lock should succeed."""
        anima_id = str(uuid4())
        with advisory_lock("test_anima_lock", anima_id=anima_id) as acquired:
            assert acquired is True


class TestAdvisoryLockContention:
    """Cross-connection contention behavior."""

    def test_second_connection_gets_false(self):
        """Second connection trying same lock should get False."""
        lock_name = f"test_contention_{uuid4().hex[:8]}"

        with advisory_lock(lock_name) as first_acquired:
            assert first_acquired is True

            # Second connection tries same lock — should fail
            with advisory_lock(lock_name) as second_acquired:
                assert second_acquired is False

    def test_anima_lock_contention(self):
        """Two connections competing for same anima lock."""
        lock_name = f"test_anima_contention_{uuid4().hex[:8]}"
        anima_id = str(uuid4())

        with advisory_lock(lock_name, anima_id=anima_id) as first:
            assert first is True

            with advisory_lock(lock_name, anima_id=anima_id) as second:
                assert second is False


class TestAdvisoryLockIsolation:
    """Locks on different keys don't interfere."""

    def test_different_animas_dont_block(self):
        """Lock on anima A should not block anima B."""
        lock_name = f"test_isolation_{uuid4().hex[:8]}"
        anima_a = str(uuid4())
        anima_b = str(uuid4())

        with advisory_lock(lock_name, anima_id=anima_a) as acquired_a:
            assert acquired_a is True

            with advisory_lock(lock_name, anima_id=anima_b) as acquired_b:
                assert acquired_b is True

    def test_different_workflows_dont_block(self):
        """Lock on workflow X should not block workflow Y."""
        with advisory_lock(f"workflow_x_{uuid4().hex[:8]}") as acquired_x:
            assert acquired_x is True

            with advisory_lock(f"workflow_y_{uuid4().hex[:8]}") as acquired_y:
                assert acquired_y is True


class TestAdvisoryLockExceptionSafety:
    """Lock released even if wrapped code raises."""

    def test_lock_released_on_exception(self):
        """Lock should auto-release when exception occurs inside context."""
        lock_name = f"test_exception_{uuid4().hex[:8]}"

        with pytest.raises(ValueError):
            with advisory_lock(lock_name) as acquired:
                assert acquired is True
                raise ValueError("intentional error")

        # Lock should be free now — reacquire succeeds
        with advisory_lock(lock_name) as acquired:
            assert acquired is True

    def test_anima_lock_released_on_exception(self):
        """Per-anima lock should auto-release on exception."""
        lock_name = f"test_anima_exception_{uuid4().hex[:8]}"
        anima_id = str(uuid4())

        with pytest.raises(RuntimeError):
            with advisory_lock(lock_name, anima_id=anima_id) as acquired:
                assert acquired is True
                raise RuntimeError("intentional error")

        with advisory_lock(lock_name, anima_id=anima_id) as acquired:
            assert acquired is True


class TestAdvisoryLockNotAcquiredPath:
    """Verify behavior when lock is not acquired."""

    def test_code_inside_context_still_runs(self):
        """When lock not acquired, context body still executes (with False)."""
        lock_name = f"test_not_acquired_{uuid4().hex[:8]}"
        executed = False

        with advisory_lock(lock_name) as first:
            assert first is True

            with advisory_lock(lock_name) as second:
                assert second is False
                executed = True  # Code still runs, caller decides what to do

        assert executed is True
