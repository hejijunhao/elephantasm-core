"""
Knowledge Retrieval - Domain Logic for Pack Compiler

Specialized retrieval operations for knowledge in pack compilation.
Wraps KnowledgeOperations.search_similar with multi-type support.

Pattern: Sync static methods, session passed explicitly.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlmodel import Session

from app.models.database.knowledge import Knowledge, KnowledgeType


class KnowledgeRetrieval:
    """
    Retrieval operations for Pack Compiler.

    Focuses on semantic search with multi-type filtering.
    """

    @staticmethod
    def search_similar(
        session: Session,
        anima_id: UUID,
        query_embedding: List[float],
        limit: int = 10,
        threshold: float = 0.7,
        knowledge_types: Optional[List[KnowledgeType]] = None,
    ) -> List[tuple[Knowledge, float]]:
        """
        Find knowledge similar to query embedding.

        Supports filtering by multiple knowledge types (OR logic).

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            query_embedding: Query vector (1536 dimensions)
            limit: Max results
            threshold: Minimum similarity (0-1)
            knowledge_types: Types to include (None = all)

        Returns:
            List of (Knowledge, similarity) tuples, sorted by similarity DESC
        """
        # Convert similarity threshold to distance threshold
        # Cosine distance: 0 = identical, 2 = opposite
        max_distance = 1 - threshold

        # Build conditions
        conditions = [
            Knowledge.anima_id == anima_id,
            Knowledge.is_deleted.is_(False),
            Knowledge.embedding.isnot(None),
            Knowledge.embedding.cosine_distance(query_embedding) < max_distance,
        ]

        # Type filter (OR across types)
        if knowledge_types:
            conditions.append(Knowledge.knowledge_type.in_(knowledge_types))

        # Execute query with distance calculation
        result = session.execute(
            select(
                Knowledge,
                Knowledge.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(and_(*conditions))
            .order_by("distance")
            .limit(min(limit, 100))
        )

        # Convert distance to similarity (1 - distance)
        return [(knowledge, 1 - distance) for knowledge, distance in result.all()]

    @staticmethod
    def get_by_types(
        session: Session,
        anima_id: UUID,
        knowledge_types: List[KnowledgeType],
        limit: int = 50,
    ) -> List[Knowledge]:
        """
        Get knowledge entries by types (no semantic search).

        Used when we need knowledge without a query (e.g., fetching all facts).

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            knowledge_types: Types to include
            limit: Max results

        Returns:
            List of knowledge entries ordered by created_at DESC
        """
        conditions = [
            Knowledge.anima_id == anima_id,
            Knowledge.is_deleted.is_(False),
        ]

        if knowledge_types:
            conditions.append(Knowledge.knowledge_type.in_(knowledge_types))

        result = session.execute(
            select(Knowledge)
            .where(and_(*conditions))
            .order_by(Knowledge.created_at.desc())
            .limit(min(limit, 100))
        )

        return list(result.scalars().all())

    @staticmethod
    def get_with_embeddings(
        session: Session,
        anima_id: UUID,
        knowledge_types: Optional[List[KnowledgeType]] = None,
        limit: int = 100,
    ) -> List[Knowledge]:
        """
        Get knowledge entries that have embeddings.

        Used when we need to compute similarity scores manually.

        Args:
            session: Database session
            anima_id: Anima to retrieve for
            knowledge_types: Types to include (None = all)
            limit: Max results

        Returns:
            List of knowledge entries with embeddings
        """
        conditions = [
            Knowledge.anima_id == anima_id,
            Knowledge.is_deleted.is_(False),
            Knowledge.embedding.isnot(None),
        ]

        if knowledge_types:
            conditions.append(Knowledge.knowledge_type.in_(knowledge_types))

        result = session.execute(
            select(Knowledge)
            .where(and_(*conditions))
            .order_by(Knowledge.created_at.desc())
            .limit(min(limit, 200))
        )

        return list(result.scalars().all())
