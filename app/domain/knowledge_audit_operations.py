from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlmodel import select

from app.models.database.knowledge_audit_log import (
    KnowledgeAuditLog,
    AuditLogCreate,
)


class KnowledgeAuditOperations:
    """Domain operations for Knowledge audit log."""

    @staticmethod
    def create(session: Session, data: AuditLogCreate) -> KnowledgeAuditLog:
        """Create audit log entry."""
        log_entry = KnowledgeAuditLog.model_validate(data)
        session.add(log_entry)
        session.flush()
        session.refresh(log_entry)
        return log_entry

    @staticmethod
    def get_by_knowledge_id(
        session: Session,
        knowledge_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[KnowledgeAuditLog]:
        """Get audit log for specific Knowledge entry."""
        stmt = select(KnowledgeAuditLog).where(
            KnowledgeAuditLog.knowledge_id == knowledge_id
        ).order_by(KnowledgeAuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_by_source_id(
        session: Session,
        source_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[KnowledgeAuditLog]:
        """Get audit logs triggered by specific source (e.g., Memory)."""
        stmt = select(KnowledgeAuditLog).where(
            KnowledgeAuditLog.source_id == source_id
        ).order_by(KnowledgeAuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_provenance_chain(
        session: Session,
        knowledge_id: UUID
    ) -> List[KnowledgeAuditLog]:
        """
        Get provenance chain: all source Memories that contributed to Knowledge.
        Returns logs with source_id (Memory UUID) in chronological order.
        """
        stmt = select(KnowledgeAuditLog).where(
            KnowledgeAuditLog.knowledge_id == knowledge_id,
            KnowledgeAuditLog.source_id.isnot(None)
        ).order_by(KnowledgeAuditLog.created_at)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_influenced_knowledge(
        session: Session,
        memory_id: UUID
    ) -> List[UUID]:
        """
        Get all Knowledge IDs influenced by a specific Memory.
        Useful for reverse provenance queries.
        """
        stmt = select(KnowledgeAuditLog.knowledge_id).where(
            KnowledgeAuditLog.source_id == memory_id
        ).distinct()
        return list(session.exec(stmt).all())
