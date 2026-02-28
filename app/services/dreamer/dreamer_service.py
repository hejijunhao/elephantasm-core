"""
Dreamer Service - Memory Curation Workflow

Native Python orchestration for the Dreamer workflow.
Processes memories through Light Sleep (algorithmic) and Deep Sleep (LLM) phases.

Usage:
    # From API route (async with BackgroundTasks)
    background_tasks.add_task(run_dream_background, anima_id, session_id, user_id)

    # From scheduler (sync, with RLS context)
    with get_db_with_rls_context(user_id) as db:
        dreamer = DreamerService(db)
        dreamer.run_dream(anima_id, session_id)
"""

import logging
from typing import Optional
from uuid import UUID

from sqlmodel import Session

from app.core.database import get_db_with_rls_context
from app.domain.dreamer_operations import DreamerOperations
from app.models.database.dreams import DreamSession, DreamStatus
from app.services.dreamer.config import DreamerConfig
from app.services.dreamer.deep_sleep import DeepSleepResults, run_deep_sleep
from app.services.dreamer.gather import DreamContext, gather_dream_context
from app.services.dreamer.light_sleep import LightSleepResults, run_light_sleep

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Background Task Entry Point
# ─────────────────────────────────────────────────────────────────


def run_dream_background(anima_id: UUID, session_id: UUID, user_id: UUID) -> None:
    """
    Background task entry point for dream execution.

    Called by FastAPI BackgroundTasks after API returns 202.
    Creates its own database session since background tasks
    run outside the request lifecycle.

    Args:
        anima_id: Target Anima
        session_id: Pre-created DreamSession ID (RUNNING state)
        user_id: Owner's user ID (required for RLS context)
    """
    logger.info(f"Background dream starting: anima={anima_id}, session={session_id}")

    error_message: str | None = None

    with get_db_with_rls_context(user_id) as db:
        try:
            dreamer = DreamerService(db)
            dreamer.run_dream(anima_id=anima_id, session_id=session_id)
            db.commit()
            logger.info(f"Background dream completed: session={session_id}")
        except Exception as e:
            db.rollback()
            error_message = str(e)
            logger.error(f"Background dream failed: {e}", exc_info=True)

    # Mark session as failed if error occurred
    # Needs fresh RLS context since rollback clears transaction-scoped SET LOCAL
    if error_message:
        try:
            with get_db_with_rls_context(user_id) as fail_db:
                DreamerOperations.fail_session(fail_db, session_id, error_message)
        except Exception as fail_err:
            logger.error(f"Failed to mark session as failed: {fail_err}")


# ─────────────────────────────────────────────────────────────────
# Main Orchestrator
# ─────────────────────────────────────────────────────────────────


class DreamerService:
    """
    Orchestrates the Dreamer workflow for memory curation.

    Two-phase processing:
    1. Light Sleep - Algorithmic (decay, transitions, flagging)
    2. Deep Sleep - LLM-powered (merge, split, refine) [Phase 3]
    """

    def __init__(self, session: Session, config: DreamerConfig | None = None):
        """
        Initialize DreamerService.

        Args:
            session: Database session (caller manages transactions)
            config: Optional custom configuration (defaults sensible)
        """
        self.session = session
        self.config = config or DreamerConfig()

    def run_dream(self, anima_id: UUID, session_id: UUID) -> DreamSession:
        """
        Execute a full dream cycle for an Anima.

        Session must be pre-created by API route before calling this.

        Args:
            anima_id: The Anima to dream for
            session_id: Pre-created DreamSession ID (RUNNING state)

        Returns:
            Completed DreamSession with metrics and summary
        """
        logger.info(f"Executing dream: anima={anima_id}, session={session_id}")

        # Fetch existing session
        dream_session = self.session.get(DreamSession, session_id)
        if not dream_session:
            raise ValueError(f"Dream session {session_id} not found")

        if dream_session.status != DreamStatus.RUNNING:
            raise ValueError(
                f"Dream session {session_id} is not RUNNING "
                f"(status: {dream_session.status})"
            )

        # Store config snapshot for reproducibility
        dream_session.config_snapshot = self.config.to_dict()
        self.session.flush()

        try:
            # Phase 1: Gather context
            context = gather_dream_context(
                self.session,
                anima_id=anima_id,
                since_last_dream=True,
            )

            if not context.memories:
                logger.info(f"No memories to process for anima {anima_id}")
                return self._complete_session(
                    dream_session, "No memories to process."
                )

            # Update metrics
            dream_session.memories_reviewed = len(context.memories)
            self.session.flush()

            # Phase 2: Light Sleep (algorithmic)
            light_results = run_light_sleep(
                self.session,
                dream_session=dream_session,
                context=context,
                config=self.config,
            )

            # Phase 3: Deep Sleep (LLM-powered)
            deep_results = run_deep_sleep(
                self.session,
                dream_session=dream_session,
                context=context,
                light_results=light_results,
                config=self.config,
            )

            # Phase 4: Generate summary and complete
            summary = self._generate_summary(dream_session, light_results, deep_results)
            return self._complete_session(dream_session, summary)

        except Exception as e:
            logger.error(f"Dream failed for anima {anima_id}: {e}", exc_info=True)
            return self._fail_session(dream_session, str(e))

    def _complete_session(
        self, dream_session: DreamSession, summary: str
    ) -> DreamSession:
        """Mark dream session as completed."""
        return DreamerOperations.complete_session(
            self.session,
            session_id=dream_session.id,
            summary=summary,
        )

    def _fail_session(self, dream_session: DreamSession, error: str) -> DreamSession:
        """Mark dream session as failed."""
        return DreamerOperations.fail_session(
            self.session,
            session_id=dream_session.id,
            error_message=error,
        )

    def _generate_summary(
        self,
        dream_session: DreamSession,
        light_results: LightSleepResults,
        deep_results: DeepSleepResults | None = None,
    ) -> str:
        """
        Generate human-readable summary of dream actions.

        Combines metrics from both Light Sleep and Deep Sleep phases.
        """
        parts: list[str] = []

        # Report session metrics (updated by both phases)
        if dream_session.memories_archived > 0:
            parts.append(f"Archived {dream_session.memories_archived} stale memories")

        if dream_session.memories_created > 0:
            parts.append(f"Created {dream_session.memories_created} merged memories")

        if dream_session.memories_modified > 0:
            parts.append(f"Refined {dream_session.memories_modified} memories")

        if dream_session.memories_deleted > 0:
            parts.append(f"Removed {dream_session.memories_deleted} noise memories")

        # Report Deep Sleep specifics if available
        if deep_results:
            if deep_results.splits_completed > 0:
                parts.append(f"Split {deep_results.splits_completed} conflated memories")

            # Report errors if any (non-fatal)
            if deep_results.errors:
                parts.append(
                    f"Encountered {len(deep_results.errors)} non-fatal errors"
                )

        if not parts:
            return "No changes needed. Memory structure is coherent."

        return "Dream complete. " + ". ".join(parts) + "."
