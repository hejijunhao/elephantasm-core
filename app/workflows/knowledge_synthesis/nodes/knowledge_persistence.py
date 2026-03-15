"""
Knowledge Persistence

Persists extracted Knowledge items to database with deduplication and audit logging.
Final step — writes validated Knowledge with provenance links.

Uses RLS context for write operations (multi-tenant security).
Atomic transaction — all-or-nothing (rollback on error).
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

from ..config import (
    DEDUPLICATION_STRATEGY,
    AUDIT_TRIGGERED_BY,
    ERROR_DB_WRITE_FAILED,
)
from app.domain.knowledge_operations import KnowledgeOperations
from app.domain.knowledge_audit_operations import KnowledgeAuditOperations
from app.models.database.knowledge import KnowledgeCreate, KnowledgeType, SourceType, AuditAction
from app.models.database.knowledge_audit_log import AuditLogCreate
from app.workflows.utils.rls_context import get_user_id_for_anima, session_with_rls_context


@dataclass
class KnowledgePersistenceResult:
    """Result from knowledge persistence step."""

    knowledge_ids: list[str] = field(default_factory=list)
    deleted_count: int = 0
    created_count: int = 0
    error: Optional[str] = None


def persist_knowledge(
    memory_id: str,
    anima_id: str,
    llm_response: List[Dict[str, Any]],
) -> KnowledgePersistenceResult:
    """
    Persist Knowledge items to database with RLS context.

    Handles deduplication, bulk insert, and audit logging in atomic transaction.
    Errors are captured in the result, not raised.

    Args:
        memory_id: UUID string of source Memory
        anima_id: UUID string of owning Anima
        llm_response: Validated Knowledge item dicts from LLM step

    Returns:
        KnowledgePersistenceResult with created IDs, counts, or error
    """
    # Empty response is valid (no extractions)
    if not llm_response or len(llm_response) == 0:
        return KnowledgePersistenceResult()

    # Parse UUIDs
    try:
        memory_uuid = UUID(memory_id)
        anima_uuid = UUID(anima_id)
    except (ValueError, KeyError) as e:
        return KnowledgePersistenceResult(error=f"Invalid UUID: {str(e)}")

    # Get user_id for RLS context
    try:
        user_id = get_user_id_for_anima(anima_uuid)
    except Exception as e:
        return KnowledgePersistenceResult(error=f"Failed to resolve Anima ownership: {str(e)}")

    # Persist with RLS context (atomic transaction)
    try:
        with session_with_rls_context(user_id) as session:
            # Deduplication: Delete existing Knowledge with source_id=memory_id
            deleted_count = 0
            if DEDUPLICATION_STRATEGY == "replace":
                deleted_count = _delete_existing_knowledge(session, memory_uuid)
            elif DEDUPLICATION_STRATEGY == "skip":
                existing_count = _count_existing_knowledge(session, memory_uuid)
                if existing_count > 0:
                    logger.info(f"Skipping: {existing_count} Knowledge items already exist for Memory {memory_id}")
                    return KnowledgePersistenceResult()
            # else: "append" strategy - no deletion, just insert

            # Bulk insert new Knowledge items
            logger.info(f"Persisting {len(llm_response)} Knowledge items for Memory {memory_id}")
            knowledge_ids = []
            for idx, item in enumerate(llm_response):
                try:
                    knowledge_id = _create_knowledge_item(
                        session,
                        anima_uuid,
                        memory_uuid,
                        item
                    )
                    knowledge_ids.append(str(knowledge_id))
                except Exception as e:
                    logger.error(f"Failed to create Knowledge item {idx+1}: {str(e)}", exc_info=True)
                    # Continue with other items (partial success allowed)
                    continue

            session.flush()

            created_count = len(knowledge_ids)
            logger.info(f"Persisted {created_count} Knowledge items for Memory {memory_id} (deleted: {deleted_count})")

    except Exception as e:
        return KnowledgePersistenceResult(error=f"{ERROR_DB_WRITE_FAILED}: {str(e)}")

    return KnowledgePersistenceResult(
        knowledge_ids=knowledge_ids,
        deleted_count=deleted_count,
        created_count=created_count,
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _delete_existing_knowledge(session, memory_id: UUID) -> int:
    """
    Delete existing Knowledge items created from a specific Memory.
    Implements "replace" deduplication strategy.
    Soft deletes (sets is_deleted=True) to preserve audit trail.
    """
    from sqlalchemy import update, select
    from app.models.database.knowledge import Knowledge
    from app.models.database.knowledge_audit_log import KnowledgeAuditLog, AuditAction

    knowledge_ids_query = select(KnowledgeAuditLog.knowledge_id).where(
        KnowledgeAuditLog.source_id == memory_id,
        KnowledgeAuditLog.action == AuditAction.CREATE
    ).distinct()

    knowledge_ids = [row[0] for row in session.execute(knowledge_ids_query)]

    if not knowledge_ids:
        return 0

    result = session.execute(
        update(Knowledge)
        .where(Knowledge.id.in_(knowledge_ids), Knowledge.is_deleted.is_(False))
        .values(is_deleted=True)
    )

    session.flush()
    return result.rowcount


def _count_existing_knowledge(session, memory_id: UUID) -> int:
    """
    Count existing Knowledge items created from a specific Memory.
    Used for "skip" deduplication strategy.
    """
    from sqlalchemy import select, func
    from app.models.database.knowledge import Knowledge
    from app.models.database.knowledge_audit_log import KnowledgeAuditLog, AuditAction

    knowledge_ids_subquery = select(KnowledgeAuditLog.knowledge_id).where(
        KnowledgeAuditLog.source_id == memory_id,
        KnowledgeAuditLog.action == AuditAction.CREATE
    ).distinct().subquery()

    result = session.execute(
        select(func.count(Knowledge.id))
        .where(
            Knowledge.id.in_(select(knowledge_ids_subquery)),
            Knowledge.is_deleted.is_(False)
        )
    )

    return result.scalar() or 0


def _create_knowledge_item(
    session,
    anima_id: UUID,
    memory_id: UUID,
    item: Dict[str, Any]
) -> UUID:
    """
    Create single Knowledge item with audit log.

    Raises:
        Exception: If creation or audit log fails
    """
    knowledge_type = KnowledgeType(item["knowledge_type"])

    create_data = KnowledgeCreate(
        anima_id=anima_id,
        knowledge_type=knowledge_type,
        content=item["content"],
        summary=item["summary"],
        topic=item.get("topic"),
        confidence=item.get("confidence"),
        source_type=SourceType.INTERNAL,
    )

    knowledge = KnowledgeOperations.create(session, create_data)
    session.flush()
    session.refresh(knowledge)

    # Create audit log
    audit_data = AuditLogCreate(
        knowledge_id=knowledge.id,
        action=AuditAction.CREATE,
        source_type=SourceType.INTERNAL,
        source_id=memory_id,
        before_state=None,
        after_state=knowledge.model_dump(mode='json'),
        triggered_by=AUDIT_TRIGGERED_BY,
    )
    KnowledgeAuditOperations.create(session, audit_data)

    # Generate embedding (best-effort)
    _generate_embedding(session, knowledge.id)

    session.flush()
    return knowledge.id


def _generate_embedding(session, knowledge_id: UUID) -> bool:
    """
    Generate embedding for newly created knowledge.
    Best-effort: logs warning on failure but doesn't raise.
    """
    try:
        KnowledgeOperations.generate_embedding(session, knowledge_id)
        logger.debug(f"Generated embedding for Knowledge {knowledge_id}")
        return True
    except Exception as e:
        logger.warning(f"Embedding generation failed for Knowledge {knowledge_id}: {str(e)}")
        return False
