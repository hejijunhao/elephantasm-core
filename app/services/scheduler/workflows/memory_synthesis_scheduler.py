"""
Memory Synthesis Workflow Scheduler

Orchestrates periodic memory synthesis for all animas.
"""
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID
import logging

from app.core.database import get_db_session
from app.domain.anima_operations import AnimaOperations
from app.workflows.memory_synthesis import get_memory_synthesis_graph
from app.workflows.memory_synthesis.config import SYNTHESIS_JOB_INTERVAL_HOURS
from ..scheduler_base import SchedulerBase

logger = logging.getLogger(__name__)


class MemorySynthesisScheduler(SchedulerBase):
    """Memory synthesis workflow scheduler."""

    @property
    def workflow_name(self) -> str:
        return "memory_synthesis"

    @property
    def job_interval_hours(self) -> int:
        return SYNTHESIS_JOB_INTERVAL_HOURS

    async def execute_for_anima(self, anima_id: UUID) -> Dict[str, Any]:
        """
        Run synthesis for single anima.

        Args:
            anima_id: UUID of anima

        Returns:
            Result dict with keys: success, skipped, error, item_id
        """
        try:
            # Get compiled graph
            graph = await get_memory_synthesis_graph()

            # Execute workflow
            result = await graph.ainvoke(
                {"anima_id": str(anima_id)},
                config={"configurable": {"thread_id": str(anima_id)}}
            )

            # Check if synthesis was triggered
            if not result.get("synthesis_triggered"):
                logger.debug(f"Anima {anima_id}: Synthesis skipped (below threshold)")
                return {
                    "success": True,
                    "skipped": True,
                    "anima_id": str(anima_id),
                }

            # Check if memory was created
            memory_id = result.get("memory_id")
            if memory_id:
                logger.info(f"Anima {anima_id}: Memory created ({memory_id})")
                return {
                    "success": True,
                    "skipped": False,
                    "anima_id": str(anima_id),
                    "item_id": memory_id,  # Generic "item_id" for base class
                }
            else:
                logger.warning(f"Anima {anima_id}: Synthesis triggered but no memory created")
                return {
                    "success": False,
                    "skipped": False,
                    "anima_id": str(anima_id),
                    "error": "Synthesis triggered but no memory created",
                }

        except Exception as e:
            logger.error(f"Anima {anima_id}: Synthesis failed - {str(e)}", exc_info=True)
            return {
                "success": False,
                "skipped": False,
                "anima_id": str(anima_id),
                "error": str(e),
            }

    async def execute_for_all_animas(self) -> Dict[str, Any]:
        """
        Run synthesis for all animas (scheduled job).

        Returns:
            Aggregated statistics
        """
        run_start = datetime.utcnow()
        logger.info("Starting memory synthesis for all animas")

        # Fetch all active animas
        with get_db_session() as session:
            animas = AnimaOperations.get_all(session, limit=1000, include_deleted=False)

        total_animas = len(animas)
        logger.info(f"Found {total_animas} animas to process")

        # Process in parallel
        tasks = [self.execute_for_anima(anima.id) for anima in animas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate statistics
        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        failed = sum(1 for r in results if isinstance(r, dict) and not r.get("success"))
        skipped = sum(1 for r in results if isinstance(r, dict) and r.get("skipped"))
        items_created = sum(1 for r in results if isinstance(r, dict) and r.get("item_id"))

        # Update stats
        self._last_run = run_start
        self._stats["total_runs"] += 1
        self._stats["animas_processed"] += total_animas
        self._stats["items_created"] += items_created

        if failed == 0:
            self._stats["successful_runs"] += 1
        else:
            self._stats["failed_runs"] += 1

        logger.info(
            f"Memory synthesis complete: {successful} successful, {failed} failed, "
            f"{skipped} skipped, {items_created} memories created"
        )

        return {
            "total_animas": total_animas,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "items_created": items_created,
            "run_time": (datetime.utcnow() - run_start).total_seconds(),
        }


# Singleton instance
_memory_synthesis_scheduler: Optional[MemorySynthesisScheduler] = None


def get_memory_synthesis_scheduler() -> MemorySynthesisScheduler:
    """Get or create memory synthesis scheduler singleton."""
    global _memory_synthesis_scheduler
    if _memory_synthesis_scheduler is None:
        _memory_synthesis_scheduler = MemorySynthesisScheduler()
    return _memory_synthesis_scheduler
