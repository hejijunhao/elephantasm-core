"""
Knowledge Persistence Node

Persists extracted Knowledge items to database with deduplication and audit logging.
Final node - writes validated Knowledge with provenance links.

CRITICAL: Uses RLS context for write operations (multi-tenant security).
Atomic transaction - all-or-nothing (rollback on error).
"""
import logging
from uuid import UUID
from typing import List, Dict, Any
from langsmith import traceable
from ..state import KnowledgeSynthesisState

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


@traceable(name="persist_knowledge", tags=["db_write", "audit", "rls", "critical"])
def persist_knowledge_node(state: KnowledgeSynthesisState) -> dict:
    """
    Persist Knowledge items to database with RLS context.

    Sync node (runs in thread pool via FastAPI).
    Handles deduplication, bulk insert, and audit logging in atomic transaction.

    ⚠️ RLS Context: Write operations use RLS for security.
    Ensures workflow can only write Knowledge for user's Anima.

    Args:
        state: Current workflow state with llm_response, memory_id, memory_data

    Returns:
        State updates:
        - knowledge_ids: List of created Knowledge UUIDs (may be empty)
        - deleted_count: Number of previous Knowledge items deleted (deduplication)
        - created_count: Number of new Knowledge items created
        - error: Error message if persistence fails

    Raises:
        No exceptions raised - errors captured in state
    """
    llm_response = state.get("llm_response", [])
    memory_id_str = state["memory_id"]
    memory_data = state.get("memory_data", {})

    # Empty response is valid (no extractions)
    if not llm_response or len(llm_response) == 0:
        return {
            "knowledge_ids": [],
            "deleted_count": 0,
            "created_count": 0,
        }

    # Parse UUIDs
    try:
        memory_id = UUID(memory_id_str)
        anima_id = UUID(memory_data["anima_id"])
    except (ValueError, KeyError) as e:
        return {
            "error": f"Invalid UUID in state: {str(e)}",
            "knowledge_ids": [],
            "deleted_count": 0,
            "created_count": 0,
        }

    # Get user_id for RLS context
    try:
        user_id = get_user_id_for_anima(anima_id)
    except Exception as e:
        return {
            "error": f"Failed to resolve Anima ownership: {str(e)}",
            "knowledge_ids": [],
            "deleted_count": 0,
            "created_count": 0,
        }

    # Persist with RLS context (atomic transaction)
    try:
        with session_with_rls_context(user_id) as session:
            # Deduplication: Delete existing Knowledge with source_id=memory_id
            deleted_count = 0
            if DEDUPLICATION_STRATEGY == "replace":
                deleted_count = _delete_existing_knowledge(session, memory_id)
            elif DEDUPLICATION_STRATEGY == "skip":
                # Check if Knowledge already exists for this Memory
                existing_count = _count_existing_knowledge(session, memory_id)
                if existing_count > 0:
                    print(f"⚠️  Skipping synthesis: {existing_count} Knowledge items already exist for Memory {memory_id}")
                    return {
                        "knowledge_ids": [],
                        "deleted_count": 0,
                        "created_count": 0,
                    }
            # else: "append" strategy - no deletion, just insert

            # Bulk insert new Knowledge items
            logger.info(f"📝 Persisting {len(llm_response)} Knowledge items for Memory {memory_id}...")
            knowledge_ids = []
            for idx, item in enumerate(llm_response):
                try:
                    knowledge_id = _create_knowledge_item(
                        session,
                        anima_id,
                        memory_id,
                        item
                    )
                    knowledge_ids.append(str(knowledge_id))
                    logger.debug(f"  ✓ Created Knowledge {idx+1}/{len(llm_response)}: {knowledge_id}")
                except Exception as e:
                    logger.error(f"⚠️  Failed to create Knowledge item {idx+1}: {str(e)}", exc_info=True)
                    # Continue with other items (partial success allowed)
                    continue

            # Commit transaction (all inserts + audit logs)
            session.commit()

            created_count = len(knowledge_ids)
            logger.info(f"✅ Committed {created_count} Knowledge items for Memory {memory_id} (deleted: {deleted_count})")

    except Exception as e:
        return {
            "error": f"{ERROR_DB_WRITE_FAILED}: {str(e)}",
            "knowledge_ids": [],
            "deleted_count": 0,
            "created_count": 0,
        }

    return {
        "knowledge_ids": knowledge_ids,
        "deleted_count": deleted_count,
        "created_count": created_count,
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _delete_existing_knowledge(session, memory_id: UUID) -> int:
    """
    Delete existing Knowledge items created from a specific Memory.

    Implements "replace" deduplication strategy.
    Soft deletes (sets is_deleted=True) to preserve audit trail.
    Queries via audit log to find Knowledge items sourced from memory_id.

    Args:
        session: Database session with RLS context
        memory_id: Memory UUID

    Returns:
        Count of deleted Knowledge items
    """
    from sqlalchemy import update, select
    from app.models.database.knowledge import Knowledge
    from app.models.database.knowledge_audit_log import KnowledgeAuditLog, AuditAction

    # Find Knowledge IDs created from this Memory via audit log
    knowledge_ids_query = select(KnowledgeAuditLog.knowledge_id).where(
        KnowledgeAuditLog.source_id == memory_id,
        KnowledgeAuditLog.action == AuditAction.CREATE
    ).distinct()

    knowledge_ids = [row[0] for row in session.execute(knowledge_ids_query)]

    if not knowledge_ids:
        return 0

    # Soft delete those Knowledge items
    result = session.execute(
        update(Knowledge)
        .where(Knowledge.id.in_(knowledge_ids), Knowledge.is_deleted == False)
        .values(is_deleted=True)
    )

    session.flush()  # Flush but don't commit yet (atomic transaction)

    return result.rowcount


def _count_existing_knowledge(session, memory_id: UUID) -> int:
    """
    Count existing Knowledge items created from a specific Memory.

    Used for "skip" deduplication strategy.
    Queries via audit log to find Knowledge items sourced from memory_id.

    Args:
        session: Database session with RLS context
        memory_id: Memory UUID

    Returns:
        Count of existing Knowledge items
    """
    from sqlalchemy import select, func
    from app.models.database.knowledge import Knowledge
    from app.models.database.knowledge_audit_log import KnowledgeAuditLog, AuditAction

    # Find Knowledge IDs created from this Memory via audit log
    knowledge_ids_subquery = select(KnowledgeAuditLog.knowledge_id).where(
        KnowledgeAuditLog.source_id == memory_id,
        KnowledgeAuditLog.action == AuditAction.CREATE
    ).distinct().subquery()

    # Count non-deleted Knowledge items
    result = session.execute(
        select(func.count(Knowledge.id))
        .where(
            Knowledge.id.in_(select(knowledge_ids_subquery)),
            Knowledge.is_deleted == False
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

    Args:
        session: Database session with RLS context
        anima_id: Anima UUID (owner)
        memory_id: Memory UUID (source)
        item: Validated Knowledge item dict

    Returns:
        Created Knowledge UUID

    Raises:
        Exception: If creation or audit log fails
    """
    # Parse knowledge_type enum
    knowledge_type = KnowledgeType(item["knowledge_type"])

    # Build create DTO
    create_data = KnowledgeCreate(
        anima_id=anima_id,
        knowledge_type=knowledge_type,
        content=item["content"],
        summary=item["summary"],
        topic=item.get("topic"),
        confidence=item.get("confidence"),
        source_type=SourceType.EXTERNAL,  # From Memory synthesis
    )

    # Create Knowledge (uses KnowledgeOperations)
    knowledge = KnowledgeOperations.create(session, create_data)

    # Flush to get ID (don't commit yet - atomic transaction)
    session.flush()
    session.refresh(knowledge)

    # Create audit log (action=CREATE, triggered_by=workflow)
    audit_data = AuditLogCreate(
        knowledge_id=knowledge.id,
        action=AuditAction.CREATE,
        source_type=SourceType.EXTERNAL,  # From Memory synthesis
        source_id=memory_id,  # What triggered this creation
        before_state=None,  # No previous state
        after_state=knowledge.model_dump(mode='json'),  # Full snapshot
        triggered_by=AUDIT_TRIGGERED_BY,
    )
    KnowledgeAuditOperations.create(session, audit_data)

    # Flush audit log (don't commit - handled by node)
    session.flush()

    return knowledge.id
