"""
Auto Meditation Hook.

Fire-and-forget trigger that automatically invokes the Meditator
when Knowledge synthesis count reaches the per-anima threshold.

Trigger chain:
  Memory Synthesis → Memory created
    → auto_knowledge_synthesis → Knowledge created
      → auto_meditation → counter check → maybe Meditation
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def trigger_auto_meditation_check(anima_id: UUID, knowledge_count: int = 1) -> None:
    """
    Check if meditation should be triggered after Knowledge synthesis.

    Increments the per-anima counter, checks against threshold,
    and fires meditation in background if threshold reached.

    Fire-and-forget — never raises to caller.

    Args:
        anima_id: UUID of Anima whose Knowledge was just synthesized
        knowledge_count: Number of Knowledge items created (default 1)
    """
    from app.core.config import settings

    if not settings.ENABLE_BACKGROUND_JOBS:
        logger.debug(
            f"Meditation check skipped for anima {anima_id} (background jobs disabled)"
        )
        return

    try:
        _check_and_trigger(anima_id, knowledge_count)
    except Exception as e:
        logger.error(
            f"❌ Unexpected error in meditation check for anima {anima_id}: {e}",
            exc_info=True,
        )


def _check_and_trigger(anima_id: UUID, knowledge_count: int) -> None:
    """
    Increment counter and trigger meditation if threshold reached.

    Uses cron DB session (BYPASSRLS) for counter operations,
    then resolves user_id for RLS-scoped meditation execution.
    """
    from app.core.database import get_cron_db_session
    from app.domain.meditator_operations import MeditatorOperations
    from app.models.database.meditations import MeditationTriggerType

    with get_cron_db_session() as db:
        # Increment counter atomically and get threshold in one query
        count, threshold = MeditatorOperations.increment_synth_count(
            db, anima_id, count=knowledge_count
        )
        db.commit()

        if count < threshold:
            logger.debug(
                f"Meditation counter {count}/{threshold} for anima {anima_id} — not yet"
            )
            return

        # Auto-recover stale RUNNING sessions (zombie from server restart/deploy)
        # Mirrors Dreamer's stale session recovery in dreamer_scheduler.py
        _recover_stale_sessions(db, anima_id, stale_minutes=30)

        # Threshold reached — check concurrency guard
        if MeditatorOperations.has_running_session(db, anima_id):
            logger.info(
                f"⊘ Meditation threshold reached ({count}/{threshold}) for anima {anima_id} "
                f"but session already running — skipping"
            )
            return

    # Acquire advisory lock to prevent duplicate trigger across machines
    from app.services.scheduler.advisory_lock import advisory_lock

    with advisory_lock("meditator", anima_id=str(anima_id)) as acquired:
        if not acquired:
            logger.info(
                f"⊘ Meditation advisory lock not acquired for anima {anima_id} "
                f"— another machine is triggering"
            )
            return

        _create_and_fire(anima_id)


def _recover_stale_sessions(db, anima_id: UUID, stale_minutes: int = 30) -> None:
    """
    Auto-fail meditation sessions stuck in RUNNING beyond the staleness threshold.

    Mirrors Dreamer's stale session recovery. Prevents zombie sessions
    (from server restart/deploy) from permanently blocking auto-meditation.
    """
    from sqlalchemy import text

    result = db.execute(
        text("""
            UPDATE meditation_sessions
            SET status = 'FAILED',
                completed_at = NOW(),
                error_message = 'Auto-cancelled: exceeded staleness threshold ('
                    || :threshold || ' min)'
            WHERE status = 'RUNNING'
              AND anima_id = :anima_id
              AND started_at < NOW() - MAKE_INTERVAL(mins => :threshold)
            RETURNING id
        """),
        {"anima_id": str(anima_id), "threshold": stale_minutes},
    )
    recovered = result.fetchall()
    if recovered:
        db.commit()
        for row in recovered:
            logger.warning(
                f"🔄 Auto-recovered stale meditation session {row[0]} for anima {anima_id}"
            )


def _create_and_fire(anima_id: UUID) -> None:
    """
    Create meditation session and fire background task.

    Resolves user_id via RLS bypass, creates session with cron DB,
    then calls run_meditation_background synchronously (it creates its own session).
    """
    from threading import Thread

    from app.core.database import get_cron_db_session
    from app.domain.meditator_operations import MeditatorOperations
    from app.models.database.meditations import MeditationTriggerType
    from app.services.meditator.meditator_service import run_meditation_background
    from app.workflows.utils.rls_context import get_user_id_for_anima

    # Resolve user_id for RLS context in the background task
    user_id = get_user_id_for_anima(anima_id)
    if not user_id:
        logger.error(f"❌ Cannot resolve user_id for anima {anima_id} — skipping meditation")
        return

    # Create session + reset counter atomically
    with get_cron_db_session() as db:
        # Re-check running session inside lock (double-check pattern)
        if MeditatorOperations.has_running_session(db, anima_id):
            logger.info(f"⊘ Meditation session already running for anima {anima_id} (double-check)")
            return

        meditation_session = MeditatorOperations.create_session(
            db,
            anima_id=anima_id,
            trigger_type=MeditationTriggerType.AUTO,
            triggered_by=None,
        )
        session_id = meditation_session.id
        db.commit()

    logger.info(
        f"🧘 Auto-meditation triggered for anima {anima_id} — session {session_id}"
    )

    # Fire in background thread (run_meditation_background is sync, blocking)
    thread = Thread(
        target=run_meditation_background,
        args=(anima_id, session_id, user_id),
        daemon=True,
        name=f"meditation-{anima_id}",
    )
    thread.start()
