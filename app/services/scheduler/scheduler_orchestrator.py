"""
Scheduler Orchestrator

Coordinates all scheduled workflows via single APScheduler instance.
Singleton pattern - one instance serves entire application.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class SchedulerOrchestrator:
    """
    Orchestrates all scheduled workflows via shared APScheduler infrastructure.

    Singleton pattern - one instance serves entire application.
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._is_running = False

    async def start(self):
        """Start scheduler (idempotent)."""
        if self._is_running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting scheduler infrastructure")
        self._scheduler.start()
        self._is_running = True

    async def stop(self):
        """Stop scheduler gracefully."""
        if not self._is_running:
            return

        logger.info("Stopping scheduler infrastructure")
        self._scheduler.shutdown(wait=True)
        self._is_running = False

    def add_job(self, *args, **kwargs):
        """
        Register job with APScheduler.

        Delegates to underlying APScheduler instance.
        """
        return self._scheduler.add_job(*args, **kwargs)

    def get_job(self, job_id: str):
        """Get job by ID."""
        return self._scheduler.get_job(job_id)

    def get_all_jobs(self) -> List:
        """Get all registered jobs (for monitoring)."""
        return self._scheduler.get_jobs()

    def get_status(self) -> Dict[str, Any]:
        """
        Get scheduler status (all workflows).

        Returns:
            Dict with scheduler state + all registered jobs
        """
        jobs = self.get_all_jobs()

        return {
            "running": self._is_running,
            "total_jobs": len(jobs),
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": getattr(job, 'next_run_time', None).isoformat() if getattr(job, 'next_run_time', None) else None,
                }
                for job in jobs
            ]
        }


# Global singleton
_scheduler_orchestrator: Optional[SchedulerOrchestrator] = None


def get_scheduler_orchestrator() -> SchedulerOrchestrator:
    """Get or create scheduler orchestrator singleton."""
    global _scheduler_orchestrator
    if _scheduler_orchestrator is None:
        _scheduler_orchestrator = SchedulerOrchestrator()
    return _scheduler_orchestrator
