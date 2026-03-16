"""
Memory Operations - Domain Logic Layer

Business logic for Memory entity CRUD and queries.
Follows static method pattern: no instance state, session passed as parameter.
No transaction management - routes handle commits/rollbacks.
Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)
from sqlalchemy import select, and_, func, update
from sqlmodel import Session
from app.domain.exceptions import EntityNotFoundError, DomainValidationError
from app.models.database.memories import Memory, MemoryCreate, MemoryUpdate, MemoryState
from app.models.database.animas import Anima
from app.models.dto.memories import MemoryMapPoint


class MemoryOperations:
    """
    Domain operations for Memory entity.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.

    Pattern: Static methods, sync operations, no transaction management.
    Routes handle commits/rollbacks; domain layer uses flush() only.
    """

    # ═══════════════════════════════════════════════════════════════════
    # Core CRUD Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def create(session: Session, data: MemoryCreate) -> Memory:
        """
        Create new memory with Anima FK validation. Raises EntityNotFoundError if Anima not found.
        Pattern: Validate FK → create → add → flush.
        """
        # Validate Anima exists and is not soft-deleted
        anima_result = session.execute(
            select(Anima).where(
                and_(
                    Anima.id == data.anima_id,
                    Anima.is_deleted.is_(False)
                )
            )
        )
        anima = anima_result.scalar_one_or_none()
        if not anima:
            raise EntityNotFoundError("Anima", data.anima_id)

        # Create memory (all fields nullable - no defaults needed)
        memory = Memory(**data.model_dump())
        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def get_by_id(
        session: Session,
        memory_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Memory]:
        """Get memory by ID. Returns None if not found or soft-deleted (unless include_deleted=True)."""
        result = session.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()

        if not memory:
            return None

        # Filter soft-deleted unless explicitly requested
        if memory.is_deleted and not include_deleted:
            return None

        return memory

    @staticmethod
    def get_by_anima(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0,
        state: Optional[MemoryState] = None,
        include_deleted: bool = False
    ) -> List[Memory]:
        """Get memories for anima (paginated, filterable by state). Ordered by time_end DESC."""
        # Build query with filters
        conditions = [Memory.anima_id == anima_id]

        if state is not None:
            conditions.append(Memory.state == state)

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        # Execute query with ordering and pagination
        result = session.execute(
            select(Memory)
            .where(and_(*conditions))
            .order_by(Memory.time_end.desc(), Memory.created_at.desc())
            .limit(min(limit, 200))  # Cap at 200
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    def update(
        session: Session,
        memory_id: UUID,
        data: MemoryUpdate
    ) -> Memory:
        """
        Partial update of memory. Raises EntityNotFoundError if not found.

        Pattern: Fetch → modify → flush.
        """
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise EntityNotFoundError("Memory", memory_id)

        # Update only provided fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(memory, field, value)

        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def soft_delete(session: Session, memory_id: UUID) -> Memory:
        """Mark memory as deleted (provenance preservation). Raises EntityNotFoundError if not found."""
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise EntityNotFoundError("Memory", memory_id)

        memory.is_deleted = True
        session.add(memory)
        session.flush()
        # Invalidate constellation cache — remaining points are positioned relative to this one
        MemoryOperations.clear_map_coords(session, memory.anima_id)
        return memory

    @staticmethod
    def restore(session: Session, memory_id: UUID) -> Memory:
        """Restore soft-deleted memory. Raises EntityNotFoundError if not found."""
        memory = MemoryOperations.get_by_id(session, memory_id, include_deleted=True)
        if not memory:
            raise EntityNotFoundError("Memory", memory_id)

        memory.is_deleted = False
        session.add(memory)
        session.flush()
        return memory

    # ═══════════════════════════════════════════════════════════════════
    # Query Operations
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_active(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[Memory]:
        """Get only active memories for anima. Convenience wrapper for get_by_anima()."""
        return MemoryOperations.get_by_anima(
            session=session,
            anima_id=anima_id,
            limit=limit,
            offset=offset,
            state=MemoryState.ACTIVE,
            include_deleted=False
        )

    @staticmethod
    def get_by_state(
        session: Session,
        anima_id: UUID,
        state: MemoryState,
        limit: int = 50,
        offset: int = 0
    ) -> List[Memory]:
        """Get memories by lifecycle state. Convenience wrapper for get_by_anima()."""
        return MemoryOperations.get_by_anima(
            session=session,
            anima_id=anima_id,
            limit=limit,
            offset=offset,
            state=state,
            include_deleted=False
        )

    @staticmethod
    def search_by_summary(
        session: Session,
        anima_id: UUID,
        summary_query: str,
        limit: int = 50
    ) -> List[Memory]:
        """Search memories by summary text (case-insensitive partial match). Ordered by importance DESC."""
        escaped = summary_query.replace("%", r"\%").replace("_", r"\_")
        result = session.execute(
            select(Memory)
            .where(
                and_(
                    Memory.anima_id == anima_id,
                    Memory.summary.ilike(f"%{escaped}%"),
                    Memory.is_deleted.is_(False)
                )
            )
            .order_by(Memory.importance.desc())
            .limit(min(limit, 200))
        )
        return list(result.scalars().all())

    @staticmethod
    def count_by_anima(
        session: Session,
        anima_id: UUID,
        state: Optional[MemoryState] = None,
        include_deleted: bool = False
    ) -> int:
        """Count memories for anima with optional filters."""
        conditions = [Memory.anima_id == anima_id]

        if state is not None:
            conditions.append(Memory.state == state)

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        result = session.execute(
            select(func.count()).select_from(Memory).where(and_(*conditions))
        )
        return result.scalar_one()

    @staticmethod
    def count_all_states(
        session: Session,
        anima_id: UUID,
    ) -> dict[MemoryState, int]:
        """Count memories grouped by state (single query). Returns {state: count} dict."""
        rows = session.execute(
            select(Memory.state, func.count())
            .where(
                and_(
                    Memory.anima_id == anima_id,
                    Memory.is_deleted.is_(False),
                )
            )
            .group_by(Memory.state)
        ).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def get_last_memory_time(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> Optional[datetime]:
        """
        Get timestamp of most recent memory for anima.

        Returns None if anima has no memories (caller should fall back to anima.created_at).
        """
        conditions = [Memory.anima_id == anima_id]

        if not include_deleted:
            conditions.append(Memory.is_deleted.is_(False))

        result = session.execute(
            select(Memory.created_at)
            .where(and_(*conditions))
            .order_by(Memory.created_at.desc())
            .limit(1)
        )

        row = result.first()
        return row[0] if row else None

    # ═══════════════════════════════════════════════════════════════════
    # Convenience Helpers (for Dreamer and curation)
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def update_importance(
        session: Session,
        memory_id: UUID,
        importance: float
    ) -> Memory:
        """Update importance score only. Convenience wrapper for Dreamer curation."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(importance=importance)
        )

    @staticmethod
    def update_confidence(
        session: Session,
        memory_id: UUID,
        confidence: float
    ) -> Memory:
        """Update confidence score only. Convenience wrapper for Dreamer curation."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(confidence=confidence)
        )

    @staticmethod
    def transition_state(
        session: Session,
        memory_id: UUID,
        new_state: MemoryState
    ) -> Memory:
        """Update memory lifecycle state. Convenience wrapper for Dreamer state transitions."""
        return MemoryOperations.update(
            session=session,
            memory_id=memory_id,
            data=MemoryUpdate(state=new_state)
        )

    # ═══════════════════════════════════════════════════════════════════
    # Score Computation Helpers (TODO: Implement in future iteration)
    # ═══════════════════════════════════════════════════════════════════


    # ═══════════════════════════════════════════════════════════════════
    # Embedding Operations (Semantic Search)
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_embedding_text(memory: Memory) -> Optional[str]:
        """
        Get text to embed for a memory. Prefers content, falls back to summary.
        Returns None if both are empty.
        """
        text = memory.content or memory.summary
        return text.strip() if text and text.strip() else None

    @staticmethod
    def generate_embedding(session: Session, memory_id: UUID) -> Memory:
        """
        Generate and store embedding for a memory.
        Raises EntityNotFoundError if memory not found, DomainValidationError if no text to embed.
        """
        from app.services.embeddings import get_embedding_provider

        memory = MemoryOperations.get_by_id(session, memory_id)
        if not memory:
            raise EntityNotFoundError("Memory", memory_id)

        text = MemoryOperations.get_embedding_text(memory)
        if not text:
            raise DomainValidationError(f"Memory {memory_id} has no content or summary to embed")

        provider = get_embedding_provider()
        embedding = provider.embed_text(text)

        memory.embedding = embedding
        memory.embedding_model = provider.model_name
        session.add(memory)
        session.flush()
        return memory

    @staticmethod
    def search_similar(
        session: Session,
        anima_id: UUID,
        query_embedding: List[float],
        limit: int = 10,
        threshold: float = 0.7,
        state: Optional[MemoryState] = MemoryState.ACTIVE
    ) -> List[tuple[Memory, float]]:
        # Find memories similar to query embedding using cosine similarity.
        # Cosine distance: 0 = identical, 2 = opposite
        # Convert threshold to distance: distance < (1 - threshold)
        max_distance = 1 - threshold

        # Build base conditions
        conditions = [
            Memory.anima_id == anima_id,
            Memory.is_deleted.is_(False),
            Memory.embedding.isnot(None)
        ]

        if state is not None:
            conditions.append(Memory.state == state)

        # Query with distance calculation
        result = session.execute(
            select(
                Memory,
                Memory.embedding.cosine_distance(query_embedding).label('distance')
            )
            .where(and_(*conditions))
            .where(Memory.embedding.cosine_distance(query_embedding) < max_distance)
            .order_by('distance')
            .limit(min(limit, 100))
        )

        # Convert distance to similarity (1 - distance)
        return [(memory, 1 - distance) for memory, distance in result.all()]

    # ═══════════════════════════════════════════════════════════════════
    # Memory Map Operations (UMAP Projection)
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def get_memory_map(
        session: Session,
        anima_id: UUID,
        limit: int = 300,
    ) -> list[MemoryMapPoint]:
        """
        Fetch memories with embeddings, project to 2D via UMAP.

        Uses cached map_x/map_y columns when all memories have coords.
        Falls back to full UMAP recomputation on cache miss.
        Returns MemoryMapPoint DTOs with (x, y) in [0, 1].
        """
        memories = list(
            session.execute(
                select(Memory)
                .where(
                    and_(
                        Memory.anima_id == anima_id,
                        Memory.is_deleted.is_(False),
                        Memory.embedding.isnot(None),
                    )
                )
                .order_by(Memory.created_at.desc())
                .limit(min(limit, 300))
            ).scalars().all()
        )

        if not memories:
            return []

        if len(memories) == 1:
            m = memories[0]
            return [MemoryMapPoint(
                id=m.id, summary=m.summary, content=m.content,
                importance=m.importance, confidence=m.confidence,
                state=m.state.value if m.state else None,
                recency_score=m.recency_score, decay_score=m.decay_score,
                created_at=m.created_at, x=0.5, y=0.5,
            )]

        # Few memories: geometric placement (UMAP needs n_neighbors>=2, struggles with n<5)
        if len(memories) <= 4:
            # Place points evenly on a circle around center
            import math
            n = len(memories)
            results = []
            for i, m in enumerate(memories):
                angle = 2 * math.pi * i / n - math.pi / 2
                x_val = 0.5 + 0.35 * math.cos(angle)
                y_val = 0.5 + 0.35 * math.sin(angle)
                results.append(MemoryMapPoint(
                    id=m.id, summary=m.summary, content=m.content,
                    importance=m.importance, confidence=m.confidence,
                    state=m.state.value if m.state else None,
                    recency_score=m.recency_score, decay_score=m.decay_score,
                    created_at=m.created_at, x=x_val, y=y_val,
                ))
            return results

        # Check cache: all memories have map_x/map_y?
        all_cached = all(m.map_x is not None and m.map_y is not None for m in memories)

        if all_cached:
            return [
                MemoryMapPoint(
                    id=m.id, summary=m.summary, content=m.content,
                    importance=m.importance, confidence=m.confidence,
                    state=m.state.value if m.state else None,
                    recency_score=m.recency_score, decay_score=m.decay_score,
                    created_at=m.created_at, x=m.map_x, y=m.map_y,
                )
                for m in memories
            ]

        # Cache miss — run UMAP projection
        try:
            import umap

            embeddings = np.array([m.embedding for m in memories])

            reducer = umap.UMAP(
                n_components=2,
                n_neighbors=min(15, len(memories) - 1),
                min_dist=0.1,
                metric="cosine",
                random_state=42,
            )
            coords_2d = reducer.fit_transform(embeddings)
        except Exception as e:
            logger.error("UMAP projection failed for anima %s: %s", anima_id, e)
            raise DomainValidationError(
                f"Memory map projection failed — try again or reduce memory count"
            ) from e

        # Normalize to [0, 1]
        mins = coords_2d.min(axis=0)
        maxs = coords_2d.max(axis=0)
        ranges = maxs - mins
        ranges[ranges == 0] = 1  # avoid div-by-zero
        normalized = (coords_2d - mins) / ranges

        # Persist cached coords
        results = []
        for i, m in enumerate(memories):
            x_val = float(normalized[i, 0])
            y_val = float(normalized[i, 1])
            m.map_x = x_val
            m.map_y = y_val
            session.add(m)
            results.append(MemoryMapPoint(
                id=m.id, summary=m.summary, content=m.content,
                importance=m.importance, confidence=m.confidence,
                state=m.state.value if m.state else None,
                recency_score=m.recency_score, decay_score=m.decay_score,
                created_at=m.created_at, x=x_val, y=y_val,
            ))

        session.flush()
        return results

    @staticmethod
    def clear_map_coords(session: Session, anima_id: UUID) -> int:
        """
        Clear cached UMAP coordinates for all memories of an anima.
        Called when new memories are created to trigger recomputation on next map load.
        Returns count of cleared memories.
        """
        result = session.execute(
            update(Memory)
            .where(
                and_(
                    Memory.anima_id == anima_id,
                    Memory.is_deleted.is_(False),
                    Memory.map_x.isnot(None),
                )
            )
            .values(map_x=None, map_y=None)
        )
        session.flush()
        return result.rowcount

    @staticmethod
    def bulk_generate_embeddings(
        session: Session,
        anima_id: UUID,
        batch_size: int = 50
    ) -> int:
        """
        Generate embeddings for memories without one. Returns count of processed memories.
        Note: Call repeatedly until returns 0 to process all memories.
        """
        from app.services.embeddings import get_embedding_provider

        # Find memories without embeddings
        result = session.execute(
            select(Memory)
            .where(
                and_(
                    Memory.anima_id == anima_id,
                    Memory.is_deleted.is_(False),
                    Memory.embedding.is_(None)
                )
            )
            .limit(batch_size)
        )
        memories = list(result.scalars().all())

        if not memories:
            return 0

        # Prepare texts (skip memories with no content)
        texts_to_embed = []
        memories_to_update = []
        for memory in memories:
            text = MemoryOperations.get_embedding_text(memory)
            if text:
                texts_to_embed.append(text)
                memories_to_update.append(memory)

        if not texts_to_embed:
            return 0

        # Batch embed
        provider = get_embedding_provider()
        embeddings = provider.embed_batch(texts_to_embed)

        # Update memories
        for memory, embedding in zip(memories_to_update, embeddings):
            if embedding:  # Skip empty embeddings
                memory.embedding = embedding
                memory.embedding_model = provider.model_name
                session.add(memory)

        session.flush()
        return len(memories_to_update)
