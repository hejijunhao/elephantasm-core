from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlmodel import select, func

from app.models.database.knowledge import (
    Knowledge,
    KnowledgeType,
    KnowledgeCreate,
    KnowledgeUpdate,
)


class KnowledgeOperations:
    """Domain operations for Knowledge entity."""

    @staticmethod
    def create(session: Session, data: KnowledgeCreate) -> Knowledge:
        """Create new Knowledge entry."""
        knowledge = Knowledge.model_validate(data)
        session.add(knowledge)
        session.flush()
        session.refresh(knowledge)
        return knowledge

    @staticmethod
    def get_by_id(
        session: Session,
        knowledge_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Knowledge]:
        """Get Knowledge by ID."""
        stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        return session.exec(stmt).first()

    @staticmethod
    def get_all(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[Knowledge]:
        """List all Knowledge for an Anima."""
        stmt = select(Knowledge).where(Knowledge.anima_id == anima_id)
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        stmt = stmt.order_by(Knowledge.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def filter_by_type(
        session: Session,
        anima_id: UUID,
        knowledge_type: KnowledgeType,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[Knowledge]:
        """Filter Knowledge by type."""
        stmt = select(Knowledge).where(
            Knowledge.anima_id == anima_id,
            Knowledge.knowledge_type == knowledge_type
        )
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        stmt = stmt.order_by(Knowledge.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def filter_by_topic(
        session: Session,
        anima_id: UUID,
        topic: str,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False
    ) -> List[Knowledge]:
        """Filter Knowledge by topic (LLM-controlled grouping)."""
        stmt = select(Knowledge).where(
            Knowledge.anima_id == anima_id,
            Knowledge.topic == topic
        )
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        stmt = stmt.order_by(Knowledge.created_at.desc()).limit(limit).offset(offset)
        return list(session.exec(stmt).all())

    @staticmethod
    def search_content(
        session: Session,
        anima_id: UUID,
        query: str,
        limit: int = 50,
        include_deleted: bool = False
    ) -> List[Knowledge]:
        """Search Knowledge content (case-insensitive)."""
        stmt = select(Knowledge).where(
            Knowledge.anima_id == anima_id,
            Knowledge.content.ilike(f"%{query}%")
        )
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        stmt = stmt.order_by(Knowledge.created_at.desc()).limit(limit)
        return list(session.exec(stmt).all())

    @staticmethod
    def update(
        session: Session,
        knowledge_id: UUID,
        data: KnowledgeUpdate
    ) -> Knowledge:
        """Update Knowledge entry."""
        knowledge = KnowledgeOperations.get_by_id(session, knowledge_id)
        if not knowledge:
            raise ValueError(f"Knowledge {knowledge_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(knowledge, key, value)

        knowledge.updated_at = datetime.utcnow()
        session.add(knowledge)
        session.flush()
        session.refresh(knowledge)
        return knowledge

    @staticmethod
    def soft_delete(session: Session, knowledge_id: UUID) -> Knowledge:
        """Soft delete Knowledge."""
        knowledge = KnowledgeOperations.get_by_id(session, knowledge_id)
        if not knowledge:
            raise ValueError(f"Knowledge {knowledge_id} not found")

        knowledge.is_deleted = True
        knowledge.updated_at = datetime.utcnow()
        session.add(knowledge)
        session.flush()
        session.refresh(knowledge)
        return knowledge

    @staticmethod
    def restore(session: Session, knowledge_id: UUID) -> Knowledge:
        """Restore soft-deleted Knowledge."""
        knowledge = KnowledgeOperations.get_by_id(session, knowledge_id, include_deleted=True)
        if not knowledge:
            raise ValueError(f"Knowledge {knowledge_id} not found")

        knowledge.is_deleted = False
        knowledge.updated_at = datetime.utcnow()
        session.add(knowledge)
        session.flush()
        session.refresh(knowledge)
        return knowledge

    @staticmethod
    def count_all(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> int:
        """Count all Knowledge for an Anima."""
        stmt = select(func.count()).select_from(Knowledge).where(
            Knowledge.anima_id == anima_id
        )
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        return session.exec(stmt).one()

    @staticmethod
    def get_unique_topics(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> List[str]:
        """Get list of unique topics for an Anima."""
        stmt = select(Knowledge.topic).where(
            Knowledge.anima_id == anima_id,
            Knowledge.topic.isnot(None)
        ).distinct()
        if not include_deleted:
            stmt = stmt.where(Knowledge.is_deleted == False)
        return list(session.exec(stmt).all())

    @staticmethod
    def get_stats(session: Session, anima_id: UUID) -> dict:
        """Get Knowledge statistics for an Anima."""
        total = KnowledgeOperations.count_all(session, anima_id)

        # Count by type
        type_counts = {}
        for ktype in KnowledgeType:
            stmt = select(func.count()).select_from(Knowledge).where(
                Knowledge.anima_id == anima_id,
                Knowledge.knowledge_type == ktype,
                Knowledge.is_deleted == False
            )
            type_counts[ktype.value] = session.exec(stmt).one()

        # Count by source
        source_counts = {}
        stmt = select(Knowledge.source_type, func.count()).where(
            Knowledge.anima_id == anima_id,
            Knowledge.is_deleted == False
        ).group_by(Knowledge.source_type)
        for source_type, count in session.exec(stmt).all():
            source_counts[source_type.value] = count

        return {
            "total": total,
            "by_type": type_counts,
            "by_source": source_counts,
            "unique_topics": len(KnowledgeOperations.get_unique_topics(session, anima_id))
        }
