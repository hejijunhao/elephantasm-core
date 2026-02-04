"""Domain operations for Identity audit log."""

from typing import List
from uuid import UUID

from sqlalchemy.orm import Session
from sqlmodel import select

from app.models.database.identity_audit_log import (
    IdentityAuditLog,
    IdentityAuditLogCreate,
)


class IdentityAuditOperations:
    """Domain operations for Identity audit log."""

    @staticmethod
    def create(session: Session, data: IdentityAuditLogCreate) -> IdentityAuditLog:
        """Create audit log entry."""
        log_entry = IdentityAuditLog.model_validate(data)
        session.add(log_entry)
        session.flush()
        session.refresh(log_entry)
        return log_entry

    @staticmethod
    def get_by_identity_id(
        session: Session,
        identity_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[IdentityAuditLog]:
        """Get audit log for specific Identity entry."""
        stmt = select(IdentityAuditLog).where(
            IdentityAuditLog.identity_id == identity_id
        ).order_by(IdentityAuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_by_source_memory_id(
        session: Session,
        memory_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> List[IdentityAuditLog]:
        """Get audit logs triggered by specific source Memory."""
        stmt = select(IdentityAuditLog).where(
            IdentityAuditLog.source_memory_id == memory_id
        ).order_by(IdentityAuditLog.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_evolution_chain(
        session: Session,
        identity_id: UUID
    ) -> List[IdentityAuditLog]:
        """
        Get evolution chain: all changes that contributed to Identity's current state.
        Returns logs in chronological order.
        """
        stmt = select(IdentityAuditLog).where(
            IdentityAuditLog.identity_id == identity_id
        ).order_by(IdentityAuditLog.created_at)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_assessments(
        session: Session,
        identity_id: UUID,
        limit: int = 50
    ) -> List[IdentityAuditLog]:
        """Get all ASSESS action logs for tracking personality assessments over time."""
        from app.models.database.identity_audit_log import IdentityAuditAction

        stmt = select(IdentityAuditLog).where(
            IdentityAuditLog.identity_id == identity_id,
            IdentityAuditLog.action == IdentityAuditAction.ASSESS
        ).order_by(IdentityAuditLog.created_at.desc()).limit(limit)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_influenced_identities(
        session: Session,
        memory_id: UUID
    ) -> List[UUID]:
        """
        Get all Identity IDs influenced by a specific Memory.
        Useful for reverse provenance queries.
        """
        stmt = select(IdentityAuditLog.identity_id).where(
            IdentityAuditLog.source_memory_id == memory_id
        ).distinct()
        return list(session.exec(stmt).all())
