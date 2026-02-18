"""
Dreamer Workflow Scheduler

Orchestrates periodic memory curation for all animas.
Supports scheduled (every 12h) and manual (API) triggers.

The Dreamer is analogous to human sleep — it reviews, consolidates,
and refines memories through algorithmic (Light Sleep) and LLM-powered
(Deep Sleep) processing.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
import logging

from sqlalchemy import text

from app.core.database import get_db_session, get_db_with_rls_context
from app.core.rls_dependencies import get_entity_user_id_bypass_rls
from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import DreamTriggerType
from app.services.dreamer import DreamerService
from ..scheduler_base import SchedulerBase

logger = logging.getLogger(__name__)

# Dream interval: 12 hours (mimics human sleep rhythm)
DREAM_JOB_INTERVAL_HOURS = 12


class DreamerScheduler(SchedulerBase):
    """
    Dreamer workflow scheduler.

    Orchestrates memory curation for all animas on a 12-hour interval.
    Each dream cycle includes:
    - Light Sleep: Algorithmic processing (decay, transitions, flagging)
    - Deep Sleep: LLM-powered curation (merge, split, refine)
    """

    def __init__(self):
        super().__init__()
        # Track running animas to prevent concurrent dreams for same anima
        self._running: set[UUID] = set()
        self._lock = asyncio.Lock()

    @property
    def workflow_name(self) -> str:
        return "dreamer"

    @property
    def job_interval_hours(self) -> int:
        return DREAM_JOB_INTERVAL_HOURS

    async def execute_for_anima(
        self, anima_id: UUID, trigger_source: str = "scheduled"
    ) -> dict[str, Any]:
        """
        Run dream cycle for single anima.

        Concurrency guard stays async (protects _running set). All sync DB/dream
        work runs in a dedicated thread via asyncio.to_thread() so the event loop
        is never blocked and asyncio.gather() in execute_for_all_animas() can
        genuinely parallelize across animas.

        Args:
            anima_id: UUID of anima
            trigger_source: One of "scheduled" or "manual"

        Returns:
            Result dict with keys: success, skipped, error, session_id
        """
        # Concurrency guard: skip if already running for this anima
        async with self._lock:
            if anima_id in self._running:
                logger.debug(f"Anima {anima_id}: Dream already running, skipping")
                return {
                    "success": True,
                    "skipped": True,
                    "anima_id": str(anima_id),
                    "reason": "already_running",
                }
            self._running.add(anima_id)

        try:
            return await asyncio.to_thread(
                self._execute_dream_sync, anima_id, trigger_source
            )
        except Exception as e:
            logger.error(
                f"Anima {anima_id}: Dream failed - {str(e)}", exc_info=True
            )
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

    def _execute_dream_sync(
        self, anima_id: UUID, trigger_source: str
    ) -> dict[str, Any]:
        """Sync dream execution — runs in dedicated thread via asyncio.to_thread()."""
        # Get user_id for RLS context using SECURITY DEFINER helper
        with get_db_session() as temp_session:
            user_id = get_entity_user_id_bypass_rls(
                temp_session, "anima", anima_id
            )
            if not user_id:
                logger.warning(f"Anima {anima_id} not found or deleted")
                return {
                    "success": False,
                    "skipped": True,
                    "anima_id": str(anima_id),
                    "reason": "anima_not_found",
                }

        # Run dream with RLS context
        with get_db_with_rls_context(user_id) as session:
            # Concurrency guard: check for running dream in DB
            if DreamerOperations.has_running_session(session, anima_id):
                logger.debug(
                    f"Anima {anima_id}: Dream session already running in DB"
                )
                return {
                    "success": True,
                    "skipped": True,
                    "anima_id": str(anima_id),
                    "reason": "session_already_running",
                }

            # Create session
            trigger_type = (
                DreamTriggerType.MANUAL
                if trigger_source == "manual"
                else DreamTriggerType.SCHEDULED
            )
            dream_session = DreamerOperations.create_session(
                session,
                anima_id=anima_id,
                trigger_type=trigger_type,
            )
            session.flush()

            # Run dream
            dreamer = DreamerService(session)
            result = dreamer.run_dream(
                anima_id=anima_id,
                session_id=dream_session.id,
            )
            session.commit()

            logger.info(
                f"Anima {anima_id}: Dream completed (session={result.id}, "
                f"status={result.status})"
            )

            return {
                "success": result.status.value == "COMPLETED",
                "skipped": False,
                "anima_id": str(anima_id),
                "session_id": str(result.id),
                "status": result.status.value,
                "summary": result.summary,
                "memories_reviewed": result.memories_reviewed,
                "memories_modified": result.memories_modified,
                "memories_created": result.memories_created,
                "memories_archived": result.memories_archived,
                "memories_deleted": result.memories_deleted,
            }

    async def trigger_manual(self, anima_id: UUID | None = None) -> dict[str, Any]:
        """
        Manual trigger (API endpoint).

        Override base class to pass trigger_source="manual".

        Args:
            anima_id: Single anima (None = all animas)
        """
        if anima_id:
            return await self.execute_for_anima(anima_id, trigger_source="manual")
        else:
            return await self.execute_for_all_animas()

    async def execute_for_all_animas(self) -> dict[str, Any]:
        """
        Run dreams for all animas (scheduled job).

        Returns:
            Aggregated statistics
        """
        run_start = datetime.now(timezone.utc)
        logger.info("Starting dream cycle for all animas")

        # Fetch all active anima IDs — bypass RLS with direct query
        # (scheduled jobs have no user context, so ORM queries return 0 rows)
        with get_db_session() as session:
            rows = session.execute(
                text("SELECT id FROM public.animas WHERE NOT is_deleted")
            ).all()
            anima_ids = [row[0] for row in rows]

        total_animas = len(anima_ids)
        logger.info(f"Found {total_animas} animas to process")

        # Process in parallel
        tasks = [
            self.execute_for_anima(anima_id, trigger_source="scheduled")
            for anima_id in anima_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate statistics
        successful = sum(
            1 for r in results if isinstance(r, dict) and r.get("success")
        )
        failed = sum(
            1 for r in results if isinstance(r, dict) and not r.get("success")
        )
        skipped = sum(
            1 for r in results if isinstance(r, dict) and r.get("skipped")
        )
        sessions_created = sum(
            1 for r in results if isinstance(r, dict) and r.get("session_id")
        )

        # Update stats
        self._last_run = run_start
        self._stats["total_runs"] += 1
        self._stats["animas_processed"] += total_animas
        self._stats["items_created"] += sessions_created

        if failed == 0:
            self._stats["successful_runs"] += 1
        else:
            self._stats["failed_runs"] += 1

        logger.info(
            f"Dream cycle complete: {successful} successful, {failed} failed, "
            f"{skipped} skipped, {sessions_created} sessions created"
        )

        return {
            "total_animas": total_animas,
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "sessions_created": sessions_created,
            "run_time": (datetime.now(timezone.utc) - run_start).total_seconds(),
        }


# Singleton instance
_dreamer_scheduler: DreamerScheduler | None = None


def get_dreamer_scheduler() -> DreamerScheduler:
    """Get or create dreamer scheduler singleton."""
    global _dreamer_scheduler
    if _dreamer_scheduler is None:
        _dreamer_scheduler = DreamerScheduler()
    return _dreamer_scheduler
