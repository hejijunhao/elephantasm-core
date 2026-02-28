"""
Fire-and-forget pack persistence service.

Handles async persistence of compiled memory packs in background tasks.
Runs after HTTP response is sent, ensuring zero impact on response latency.
"""

import logging
from typing import Optional
from uuid import UUID

from app.core.database import get_db_with_rls_context
from app.domain.memory_pack_operations import MemoryPackOperations
from app.models.database.memory_pack import MemoryPack

logger = logging.getLogger(__name__)

# Retention policy: max packs per anima
MAX_PACKS_PER_ANIMA = 100


def persist_pack_async(pack_data: dict, anima_id: UUID, user_id: Optional[UUID] = None) -> None:
    """
    Fire-and-forget pack persistence.

    Runs in FastAPI's background thread pool after response is sent.
    Handles its own session lifecycle and error recovery.

    Args:
        pack_data: Dict with MemoryPack fields (from build_pack_data_for_persistence)
        anima_id: Anima UUID for retention policy enforcement
        user_id: User UUID for RLS context (required for multi-tenant isolation)

    Note:
        - Uses RLS-enabled session for multi-tenant isolation
        - Commits independently of main request
        - Errors are logged but don't affect the response
        - Retention cleanup runs in same transaction
    """
    try:
        with get_db_with_rls_context(user_id) as session:
            # Create pack from data
            pack = MemoryPack(**pack_data)
            saved = MemoryPackOperations.create(session, pack)

            # Enforce retention (delete old packs beyond limit)
            deleted = MemoryPackOperations.enforce_retention(
                session,
                anima_id=anima_id,
                max_packs=MAX_PACKS_PER_ANIMA
            )

            # Commit handled by context manager

            if deleted > 0:
                logger.debug(f"Pack {saved.id} persisted, {deleted} old packs pruned")
            else:
                logger.debug(f"Pack {saved.id} persisted")

    except Exception as e:
        logger.error(f"Background pack persistence failed: {e}")
