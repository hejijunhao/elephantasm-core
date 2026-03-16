"""
PostgreSQL Advisory Lock Helper

Cross-machine coordination for scheduled jobs.
Uses pg_try_advisory_lock() — non-blocking, cluster-wide, crash-safe.
"""

import logging
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import text

from app.core.database import get_cron_db_session

logger = logging.getLogger(__name__)


@contextmanager
def advisory_lock(lock_name: str, anima_id: Optional[str] = None):
    """
    Acquire PostgreSQL advisory lock. Non-blocking — yields False if already held.

    Args:
        lock_name: Job identifier (e.g., "memory_synthesis", "dreamer")
        anima_id: Optional anima UUID string for per-anima locks

    Yields:
        True if lock acquired, False if another machine holds it
    """
    with get_cron_db_session() as session:
        if anima_id:
            # Two-key lock: (workflow_hash, anima_hash)
            acquired = session.execute(
                text("""
                    SELECT pg_try_advisory_lock(
                        hashtext(:lock_name),
                        hashtext(:anima_id)
                    )
                """),
                {"lock_name": f"elephantasm:{lock_name}", "anima_id": anima_id},
            ).scalar()
        else:
            # Single-key lock: job-level
            acquired = session.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:lock_name))"),
                {"lock_name": f"elephantasm:{lock_name}"},
            ).scalar()

        if not acquired:
            logger.debug(
                f"Advisory lock not acquired: {lock_name}"
                + (f" anima={anima_id}" if anima_id else "")
                + " (another machine holds it)"
            )

        try:
            yield acquired
        finally:
            if acquired:
                if anima_id:
                    session.execute(
                        text("""
                            SELECT pg_advisory_unlock(
                                hashtext(:lock_name),
                                hashtext(:anima_id)
                            )
                        """),
                        {"lock_name": f"elephantasm:{lock_name}", "anima_id": anima_id},
                    )
                else:
                    session.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:lock_name))"),
                        {"lock_name": f"elephantasm:{lock_name}"},
                    )
