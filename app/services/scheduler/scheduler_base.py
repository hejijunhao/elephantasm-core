"""
Scheduler Base Class

Abstract base class for workflow schedulers.
Provides common patterns (statistics, manual triggers, registration).
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable
from uuid import UUID
import logging

from .scheduler_orchestrator import get_scheduler_orchestrator

logger = logging.getLogger(__name__)


class SchedulerBase(ABC):
    """
    Abstract base class for workflow schedulers.

    Subclasses implement:
    - workflow_name (property)
    - job_interval_hours (property)
    - execute_for_anima() (async method)
    - execute_for_all_animas() (async method)
    """

    def __init__(self):
        self._scheduler = get_scheduler_orchestrator()
        self._last_run: Optional[datetime] = None
        self._stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "animas_processed": 0,
            "items_created": 0,
        }

    @property
    @abstractmethod
    def workflow_name(self) -> str:
        """Workflow identifier (e.g., 'memory_synthesis')."""
        pass

    @property
    @abstractmethod
    def job_interval_hours(self) -> int:
        """How often to run (hours)."""
        pass

    @abstractmethod
    async def execute_for_anima(self, anima_id: UUID) -> Dict[str, Any]:
        """
        Execute workflow for single anima.

        Returns:
            Result dict with keys: success, skipped, error, item_id
        """
        pass

    @abstractmethod
    async def execute_for_all_animas(self) -> Dict[str, Any]:
        """
        Execute workflow for all animas.

        Returns:
            Aggregated statistics
        """
        pass

    async def register(self):
        """Register this workflow's job with scheduler."""
        job_id = f"{self.workflow_name}_job"

        self._scheduler.add_job(
            func=self.execute_for_all_animas,
            trigger='interval',
            hours=self.job_interval_hours,
            id=job_id,
            name=f"{self.workflow_name.replace('_', ' ').title()} - All Animas",
            replace_existing=True,
            max_instances=1,
        )

        logger.info(
            f"Registered {self.workflow_name} job: "
            f"job_id={job_id}, interval_hours={self.job_interval_hours}"
        )

    async def trigger_manual(self, anima_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Manual trigger (API endpoint).

        Args:
            anima_id: Single anima (None = all animas)
        """
        if anima_id:
            return await self.execute_for_anima(anima_id)
        else:
            return await self.execute_for_all_animas()

    async def execute_with_lock(
        self,
        coro_func: Callable[..., Awaitable[Dict[str, Any]]],
        *args,
        anima_id: Optional[UUID] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute coroutine under advisory lock.

        Returns None if lock not acquired (another machine is running this job).
        """
        from app.services.scheduler.advisory_lock import advisory_lock

        lock_key = self.workflow_name
        anima_key = str(anima_id) if anima_id else None

        with advisory_lock(lock_key, anima_key) as acquired:
            if not acquired:
                return None
            return await coro_func(*args, **kwargs)

    def execute_with_lock_sync(
        self,
        func: Callable[..., Dict[str, Any]],
        *args,
        anima_id: Optional[UUID] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute sync function under advisory lock.

        Returns None if lock not acquired (another machine is running this job).
        """
        from app.services.scheduler.advisory_lock import advisory_lock

        lock_key = self.workflow_name
        anima_key = str(anima_id) if anima_id else None

        with advisory_lock(lock_key, anima_key) as acquired:
            if not acquired:
                return None
            return func(*args, **kwargs)

    def get_status(self) -> Dict[str, Any]:
        """Get workflow-specific status."""
        job = self._scheduler.get_job(f"{self.workflow_name}_job")
        next_run_time = getattr(job, 'next_run_time', None) if job else None

        return {
            "workflow": self.workflow_name,
            "running": job is not None,
            "interval_hours": self.job_interval_hours,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "next_run": next_run_time.isoformat() if next_run_time else None,
            "stats": self._stats,
        }
