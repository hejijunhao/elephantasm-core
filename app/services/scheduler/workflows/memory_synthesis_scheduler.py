"""
Memory Synthesis Workflow Scheduler

Orchestrates periodic memory synthesis for all animas.
Supports scheduled (hourly), manual (API), and realtime (event-driven) triggers.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from uuid import UUID
import logging
import os

from sqlalchemy import text

from app.core.database import get_db_session
from app.workflows.memory_synthesis import get_memory_synthesis_graph
from app.workflows.memory_synthesis.config import SYNTHESIS_JOB_INTERVAL_HOURS
from app.services.hooks import trigger_auto_knowledge_synthesis
from ..scheduler_base import SchedulerBase

logger = logging.getLogger(__name__)


class MemorySynthesisScheduler(SchedulerBase):
    """Memory synthesis workflow scheduler."""

    def __init__(self):
        super().__init__()
        # Track running animas to prevent concurrent synthesis for same anima
        self._running: set[UUID] = set()
        self._lock = asyncio.Lock()

    @property
    def workflow_name(self) -> str:
        return "memory_synthesis"

    @property
    def job_interval_hours(self) -> int:
        return SYNTHESIS_JOB_INTERVAL_HOURS

    async def execute_for_anima(
        self, anima_id: UUID, trigger_source: str = "scheduled"
    ) -> Dict[str, Any]:
        """
        Run synthesis for single anima.

        Args:
            anima_id: UUID of anima
            trigger_source: One of "scheduled", "manual", or "realtime"

        Returns:
            Result dict with keys: success, skipped, error, item_id
        """
        # Concurrency guard: skip if already running for this anima
        async with self._lock:
            if anima_id in self._running:
                logger.debug(f"Anima {anima_id}: Synthesis already running, skipping")
                return {
                    "success": True,
                    "skipped": True,
                    "anima_id": str(anima_id),
                    "reason": "already_running"
                }
            self._running.add(anima_id)

        try:
            # Get compiled graph
            graph = await get_memory_synthesis_graph()

            # Build LangSmith config with trigger source
            thread_id = f"anima_{anima_id}"
            run_name = f"memory_synthesis_{trigger_source}_{str(anima_id)[:8]}"

            # Execute workflow with LangSmith tracing metadata
            result = await graph.ainvoke(
                {"anima_id": str(anima_id)},
                config={
                    "configurable": {"thread_id": thread_id},
                    "run_name": run_name,
                    "tags": ["memory_synthesis", trigger_source],
                    "metadata": {
                        "anima_id": str(anima_id),
                        "trigger_source": trigger_source,
                        "environment": os.getenv("ENV", "production"),
                    },
                }
            )

            # Check if synthesis was triggered
            if not result.get("synthesis_triggered"):
                skip_reason = result.get("skip_reason", "unknown")
                logger.debug(f"Anima {anima_id}: Synthesis skipped ({skip_reason})")
                return {
                    "success": True,
                    "skipped": True,
                    "anima_id": str(anima_id),
                    "reason": skip_reason,
                }

            # Check if memory was created
            memory_id = result.get("memory_id")
            if memory_id:
                logger.info(f"Anima {anima_id}: Memory created ({memory_id})")

                # Trigger Knowledge Synthesis automatically (fire-and-forget)
                trigger_auto_knowledge_synthesis(memory_id)

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
        finally:
            # Always remove from running set
            async with self._lock:
                self._running.discard(anima_id)

    async def check_and_enqueue_if_needed(self, anima_id: UUID) -> bool:
        """
        Check accumulation score and enqueue synthesis job if threshold reached.

        Called on every event creation (via BackgroundTasks). Fast path: just score
        calculation + conditional enqueue. Heavy workflow only runs if threshold exceeded.

        Args:
            anima_id: UUID of anima to check

        Returns:
            True if job enqueued, False if below threshold or error
        """
        try:
            # Local imports to avoid circular dependency
            from app.domain.synthesis_config_operations import SynthesisConfigOperations
            from app.domain.synthesis_metrics import compute_accumulation_score
            from app.core.database import get_db_with_rls_context
            from app.core.rls_dependencies import get_entity_user_id_bypass_rls

            # First, get user_id for the anima using SECURITY DEFINER helper
            # This bypasses RLS to solve circular dependency (need user_id to set RLS context)
            with get_db_session() as temp_session:
                user_id = get_entity_user_id_bypass_rls(temp_session, 'anima', anima_id)

                if not user_id:
                    logger.error(f"Anima {anima_id} not found or deleted")
                    return False

            # Open DB session with RLS context for the anima's owner
            with get_db_with_rls_context(user_id) as session:
                # Calculate accumulation score using domain helper
                result = compute_accumulation_score(session, anima_id)
                score = result["accumulation_score"]

                # Get threshold from anima config (may auto-create with RLS context)
                config = SynthesisConfigOperations.get_or_create_default(session, anima_id)
                threshold = config.threshold

            # Check threshold
            if score < threshold:
                logger.debug(
                    f"Anima {anima_id}: score {score:.2f} below threshold {threshold:.2f}, skipping"
                )
                return False

            # Enqueue one-off job with 5s delay (batches rapid events)
            job_id = f"memory_synthesis_realtime_{anima_id}"
            run_time = datetime.now(timezone.utc) + timedelta(seconds=5)

            self._scheduler.add_job(
                self.execute_for_anima,
                trigger="date",
                run_date=run_time,
                id=job_id,
                name=f"Memory Synthesis (realtime) {anima_id}",
                args=[anima_id, "realtime"],  # Pass trigger_source
                replace_existing=True,  # Natural dedup: replaces if exists
                coalesce=True,
                max_instances=1,  # Prevent concurrent runs
                misfire_grace_time=30
            )

            logger.info(
                f"Anima {anima_id}: score {score:.2f} >= threshold {threshold:.2f}, "
                f"enqueued synthesis job (runs in 5s)"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking synthesis threshold for anima {anima_id}: {e}")
            return False

    async def trigger_manual(self, anima_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Manual trigger (API endpoint).

        Override base class to pass trigger_source="manual" for proper LangSmith tagging.

        Args:
            anima_id: Single anima (None = all animas)
        """
        if anima_id:
            return await self.execute_for_anima(anima_id, trigger_source="manual")
        else:
            return await self.execute_for_all_animas()

    async def execute_for_all_animas(self) -> Dict[str, Any]:
        """
        Run synthesis for all animas (scheduled job).

        Returns:
            Aggregated statistics
        """
        run_start = datetime.now(timezone.utc)
        logger.info("Starting memory synthesis for all animas")

        # Fetch all active anima IDs — bypass RLS with direct query
        # (scheduled jobs have no user context, so ORM queries return 0 rows)
        with get_db_session() as session:
            rows = session.execute(
                text("SELECT id FROM public.animas WHERE NOT is_deleted")
            ).all()
            anima_ids = [row[0] for row in rows]

        total_animas = len(anima_ids)
        logger.info(f"Found {total_animas} animas to process")

        # Process in parallel with trigger_source="scheduled"
        tasks = [self.execute_for_anima(anima_id, trigger_source="scheduled") for anima_id in anima_ids]
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
            "run_time": (datetime.now(timezone.utc) - run_start).total_seconds(),
        }


# Singleton instance
_memory_synthesis_scheduler: Optional[MemorySynthesisScheduler] = None


def get_memory_synthesis_scheduler() -> MemorySynthesisScheduler:
    """Get or create memory synthesis scheduler singleton."""
    global _memory_synthesis_scheduler
    if _memory_synthesis_scheduler is None:
        _memory_synthesis_scheduler = MemorySynthesisScheduler()
    return _memory_synthesis_scheduler
