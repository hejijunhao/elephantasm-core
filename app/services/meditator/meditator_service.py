"""
Meditator Service - Knowledge Curation Workflow

Native Python orchestration for the Meditator workflow.
Processes knowledge through Reflection (algorithmic) and Contemplation (LLM) phases.

Usage:
    # From API route (async with BackgroundTasks)
    background_tasks.add_task(run_meditation_background, anima_id, session_id, user_id)

    # From auto-trigger hook
    run_meditation_background(anima_id, session_id, user_id)
"""

import logging
from uuid import UUID

from sqlmodel import Session

from app.core.database import get_db_with_rls_context
from app.domain.exceptions import DomainValidationError, EntityNotFoundError
from app.domain.meditator_operations import MeditatorOperations
from app.models.database.meditations import MeditationSession, MeditationStatus
from app.services.meditator.config import MeditatorConfig
from app.services.meditator.contemplation import ContemplationResults, run_contemplation
from app.services.meditator.gather import MeditationContext, gather_meditation_context
from app.services.meditator.reflection import ReflectionResults, run_reflection

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Background Task Entry Point
# ─────────────────────────────────────────────────────────────────


def run_meditation_background(anima_id: UUID, session_id: UUID, user_id: UUID) -> None:
    """
    Background task entry point for meditation execution.

    Called by FastAPI BackgroundTasks after API returns 202,
    or by the auto-trigger hook after knowledge synthesis.

    Creates its own database session since background tasks
    run outside the request lifecycle.
    """
    logger.info(f"Background meditation starting: anima={anima_id}, session={session_id}")

    error_message: str | None = None

    with get_db_with_rls_context(user_id) as db:
        try:
            meditator = MeditatorService(db)
            meditator.run_meditation(anima_id=anima_id, session_id=session_id)
            db.commit()
            logger.info(f"Background meditation completed: session={session_id}")
        except Exception as e:
            db.rollback()
            error_message = str(e)
            logger.error(f"Background meditation failed: {e}", exc_info=True)

    # Mark session as failed if error occurred
    # Needs fresh RLS context since rollback clears transaction-scoped SET LOCAL
    if error_message:
        try:
            with get_db_with_rls_context(user_id) as fail_db:
                MeditatorOperations.fail_session(fail_db, session_id, error_message)
                # Reset counter to prevent retry storm (inner reset was rolled back)
                MeditatorOperations.reset_synth_count(fail_db, anima_id)
                fail_db.commit()
        except Exception as fail_err:
            logger.error(f"Failed to mark meditation session as failed: {fail_err}")


# ─────────────────────────────────────────────────────────────────
# Main Orchestrator
# ─────────────────────────────────────────────────────────────────


class MeditatorService:
    """
    Orchestrates the Meditator workflow for knowledge curation.

    Two-phase processing:
    1. Reflection - Algorithmic (clustering + flagging only)
    2. Contemplation - LLM-powered (merge, split, update, reclassify, delete)
    """

    def __init__(self, session: Session, config: MeditatorConfig | None = None):
        self.session = session
        self.config = config or MeditatorConfig()

    def run_meditation(self, anima_id: UUID, session_id: UUID) -> MeditationSession:
        """
        Execute a full meditation cycle for an Anima.

        Session must be pre-created before calling this.
        """
        logger.info(f"Executing meditation: anima={anima_id}, session={session_id}")

        meditation_session = self.session.get(MeditationSession, session_id)
        if not meditation_session:
            raise EntityNotFoundError("MeditationSession", session_id)

        if meditation_session.status != MeditationStatus.RUNNING:
            raise DomainValidationError(
                f"Meditation session {session_id} is not RUNNING "
                f"(status: {meditation_session.status})"
            )

        # Store config snapshot for reproducibility
        meditation_session.config_snapshot = self.config.to_dict()
        self.session.flush()

        try:
            # Phase 1: Gather context (knowledge primary, memories context)
            context = gather_meditation_context(
                self.session,
                anima_id=anima_id,
                since_last_meditation=True,
            )

            if not context.knowledge:
                logger.info(f"No knowledge to process for anima {anima_id}")
                return self._complete_session(
                    meditation_session, "No knowledge to process."
                )

            # Update metrics
            meditation_session.knowledge_reviewed = len(context.knowledge)
            self.session.flush()

            # Phase 2: Reflection (algorithmic — clustering + flagging only)
            reflection_results = run_reflection(
                self.session,
                context=context,
                config=self.config,
            )

            # Phase 3: Contemplation (LLM — merge/split/update/reclassify/delete)
            contemplation_results = run_contemplation(
                self.session,
                meditation_session=meditation_session,
                context=context,
                reflection_results=reflection_results,
                config=self.config,
            )

            # Phase 4: Generate summary and complete
            summary = self._generate_summary(
                meditation_session, reflection_results, contemplation_results
            )
            result = self._complete_session(meditation_session, summary)

            # Phase 5: Reset synth counter AFTER successful completion
            # Must happen after _complete_session so counter isn't lost on failure
            MeditatorOperations.reset_synth_count(self.session, anima_id)

            return result

        except Exception as e:
            logger.error(f"Meditation failed for anima {anima_id}: {e}", exc_info=True)
            # Re-raise — caller (run_meditation_background) handles rollback,
            # fail_session, and counter reset in a fresh DB session
            raise

    def _complete_session(
        self, meditation_session: MeditationSession, summary: str
    ) -> MeditationSession:
        """Mark meditation session as completed."""
        return MeditatorOperations.complete_session(
            self.session,
            session_id=meditation_session.id,
            summary=summary,
        )

    def _fail_session(
        self, meditation_session: MeditationSession, error: str
    ) -> MeditationSession:
        """Mark meditation session as failed."""
        return MeditatorOperations.fail_session(
            self.session,
            session_id=meditation_session.id,
            error_message=error,
        )

    def _generate_summary(
        self,
        meditation_session: MeditationSession,
        reflection_results: ReflectionResults,
        contemplation_results: ContemplationResults | None = None,
    ) -> str:
        """Generate human-readable summary of meditation actions."""
        parts: list[str] = []

        if contemplation_results:
            if contemplation_results.clusters_processed > 0:
                parts.append(
                    f"Consolidated {contemplation_results.knowledge_consolidated_from} knowledge items "
                    f"into {contemplation_results.knowledge_consolidated_into} "
                    f"across {contemplation_results.clusters_processed} topic clusters"
                )
            if contemplation_results.merges_completed > 0:
                parts.append(f"Merged {contemplation_results.merges_completed} knowledge pairs")

        if meditation_session.knowledge_modified > 0:
            parts.append(f"Refined {meditation_session.knowledge_modified} knowledge items")

        if meditation_session.knowledge_deleted > 0:
            parts.append(f"Removed {meditation_session.knowledge_deleted} noise items")

        if contemplation_results:
            if contemplation_results.reclassifications_completed > 0:
                parts.append(
                    f"Reclassified {contemplation_results.reclassifications_completed} items"
                )
            if contemplation_results.splits_completed > 0:
                parts.append(f"Split {contemplation_results.splits_completed} conflated items")

            if contemplation_results.errors:
                parts.append(
                    f"Encountered {len(contemplation_results.errors)} non-fatal errors"
                )
                snapshot = dict(meditation_session.config_snapshot or {})
                snapshot["contemplation_errors"] = contemplation_results.errors
                meditation_session.config_snapshot = snapshot
                self.session.flush()

        if not parts:
            return "No changes needed. Knowledge base is coherent."

        return "Meditation complete. " + ". ".join(parts) + "."
