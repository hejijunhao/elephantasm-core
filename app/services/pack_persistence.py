"""
Fire-and-forget pack persistence service.

Handles async persistence of compiled memory packs in background tasks.
Runs after HTTP response is sent, ensuring zero impact on response latency.
"""

import logging
from uuid import UUID

from app.core.database import get_background_session
from app.domain.memory_pack_operations import MemoryPackOperations
from app.models.database.memory_pack import MemoryPack

logger = logging.getLogger(__name__)

# Retention policy: max packs per anima
MAX_PACKS_PER_ANIMA = 100


def persist_pack_async(pack_data: dict, anima_id: UUID) -> None:
    """
    Fire-and-forget pack persistence.

    Runs in FastAPI's background thread pool after response is sent.
    Handles its own session lifecycle and error recovery.

    Args:
        pack_data: Dict with MemoryPack fields (from build_pack_data_for_persistence)
        anima_id: Anima UUID for retention policy enforcement

    Note:
        - Uses standalone session (not request-scoped)
        - Commits independently of main request
        - Errors are logged but don't affect the response
        - Retention cleanup runs in same transaction
    """
    session = get_background_session()
    try:
        # Create pack from data
        pack = MemoryPack(**pack_data)
        saved = MemoryPackOperations.create(session, pack)

        # Enforce retention (delete old packs beyond limit)
        deleted = MemoryPackOperations.enforce_retention(
            session,
            anima_id=anima_id,
            max_packs=MAX_PACKS_PER_ANIMA
        )

        session.commit()

        if deleted > 0:
            logger.debug(f"Pack {saved.id} persisted, {deleted} old packs pruned")
        else:
            logger.debug(f"Pack {saved.id} persisted")

    except Exception as e:
        session.rollback()
        logger.error(f"Background pack persistence failed: {e}")
    finally:
        session.close()
