"""
Dreamer Domain Operations

All dream-related CRUD operations with audit trail.
Every memory mutation records a DreamAction for provenance.

Pattern: Static methods, sync operations, session passed explicitly.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlmodel import Session

from app.models.database.dreams import (
    DreamAction,
    DreamActionType,
    DreamPhase,
    DreamSession,
    DreamStatus,
    DreamTriggerType,
)
from app.models.database.memories import Memory, MemoryState


class DreamerOperations:
    """Static methods for dream operations with audit trail."""

    # ─────────────────────────────────────────────────────────────
    # Session Management
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def create_session(
        session: Session,
        anima_id: UUID,
        trigger_type: DreamTriggerType,
        triggered_by: UUID | None = None,
        config_snapshot: dict[str, Any] | None = None,
        skip_usage_tracking: bool = False,
    ) -> DreamSession:
        """
        Create a new dream session in RUNNING state.

        Args:
            session: Database session
            anima_id: Target Anima
            trigger_type: SCHEDULED or MANUAL
            triggered_by: User ID for manual triggers
            config_snapshot: DreamerConfig values at execution time
            skip_usage_tracking: Skip incrementing usage counter

        Returns:
            Created DreamSession with RUNNING status
        """
        dream = DreamSession(
            anima_id=anima_id,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            config_snapshot=config_snapshot or {},
        )
        session.add(dream)
        session.flush()
        session.refresh(dream)

        # Track synthesis run usage
        if not skip_usage_tracking:
            DreamerOperations._track_synthesis_usage(session, anima_id)

        return dream

    @staticmethod
    def _track_synthesis_usage(session: Session, anima_id: UUID) -> None:
        """Track synthesis run usage. Increments org counter."""
        from app.domain.usage_operations import UsageOperations
        from app.domain.organization_operations import OrganizationOperations
        from app.models.database.animas import Anima

        # Increment org usage counter if user is linked to org
        anima = session.get(Anima, anima_id)
        if anima and anima.user_id:
            org = OrganizationOperations.get_primary_org_for_user(session, anima.user_id)
            if org:
                UsageOperations.increment_counter(session, org.id, "synthesis_runs")

    @staticmethod
    def complete_session(
        session: Session,
        session_id: UUID,
        summary: str,
    ) -> DreamSession:
        """
        Mark dream session as COMPLETED.

        Args:
            session: Database session
            session_id: Dream session to complete
            summary: Human-readable summary of actions taken

        Returns:
            Updated DreamSession with COMPLETED status
        """
        dream = session.get(DreamSession, session_id)
        if not dream:
            raise ValueError(f"Dream session {session_id} not found")

        dream.status = DreamStatus.COMPLETED
        dream.completed_at = datetime.now(timezone.utc)
        dream.summary = summary
        session.flush()
        session.refresh(dream)
        return dream

    @staticmethod
    def fail_session(
        session: Session,
        session_id: UUID,
        error_message: str,
    ) -> DreamSession:
        """
        Mark dream session as FAILED, noting partial progress.

        DreamActions created before failure are retained for audit trail.

        Args:
            session: Database session
            session_id: Dream session to mark as failed
            error_message: Error details

        Returns:
            Updated DreamSession with FAILED status
        """
        dream = session.get(DreamSession, session_id)
        if not dream:
            raise ValueError(f"Dream session {session_id} not found")

        # Count completed actions for context
        action_count = session.scalar(
            select(func.count(DreamAction.id)).where(
                DreamAction.session_id == session_id
            )
        )

        dream.status = DreamStatus.FAILED
        dream.completed_at = datetime.now(timezone.utc)
        dream.error_message = f"Failed after {action_count} actions: {error_message}"
        session.flush()
        session.refresh(dream)
        return dream

    @staticmethod
    def get_last_session(
        session: Session,
        anima_id: UUID,
        completed_only: bool = True,
    ) -> DreamSession | None:
        """
        Get the most recent dream session for an Anima.

        Args:
            session: Database session
            anima_id: Target Anima
            completed_only: If True, only return COMPLETED sessions

        Returns:
            Most recent DreamSession or None
        """
        query = select(DreamSession).where(DreamSession.anima_id == anima_id)

        if completed_only:
            query = query.where(DreamSession.status == DreamStatus.COMPLETED)

        query = query.order_by(DreamSession.started_at.desc()).limit(1)
        return session.execute(query).scalars().first()

    @staticmethod
    def has_running_session(session: Session, anima_id: UUID) -> bool:
        """
        Check if Anima has a dream currently in progress.

        Used for concurrency guard — only one dream per Anima at a time.
        """
        result = session.exec(
            select(DreamSession.id)
            .where(DreamSession.anima_id == anima_id)
            .where(DreamSession.status == DreamStatus.RUNNING)
            .limit(1)
        ).first()
        return result is not None

    @staticmethod
    def cancel_session(
        session: Session,
        session_id: UUID,
        cancelled_by: UUID | None = None,
    ) -> DreamSession:
        """
        Cancel a running dream session.

        Used for manual recovery when a session gets stuck.
        Only RUNNING sessions can be cancelled.

        Args:
            session: Database session
            session_id: Dream session to cancel
            cancelled_by: User ID who cancelled (for audit)

        Returns:
            Updated DreamSession with FAILED status
        """
        dream = session.get(DreamSession, session_id)
        if not dream:
            raise ValueError(f"Dream session {session_id} not found")

        if dream.status != DreamStatus.RUNNING:
            raise ValueError(
                f"Cannot cancel session with status {dream.status.value}. "
                "Only RUNNING sessions can be cancelled."
            )

        dream.status = DreamStatus.FAILED
        dream.completed_at = datetime.now(timezone.utc)
        dream.error_message = (
            f"Cancelled by user {cancelled_by}" if cancelled_by
            else "Cancelled by user"
        )
        session.flush()
        session.refresh(dream)
        return dream

    # ─────────────────────────────────────────────────────────────
    # Snapshot Helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _snapshot_memory(memory: Memory) -> dict[str, Any]:
        """
        Create a JSON snapshot of a memory for audit trail.

        Captures all fields that might change during curation.
        """
        return {
            "id": str(memory.id),
            "summary": memory.summary,
            "content": memory.content,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "decay_score": memory.decay_score,
            "recency_score": memory.recency_score,
            "state": memory.state.value if memory.state else None,
            "meta": memory.meta,
            "time_start": memory.time_start.isoformat() if memory.time_start else None,
            "time_end": memory.time_end.isoformat() if memory.time_end else None,
            "is_deleted": memory.is_deleted,
        }

    @staticmethod
    def _record_action(
        session: Session,
        dream_session: DreamSession,
        action_type: DreamActionType,
        phase: DreamPhase,
        source_memory_ids: list[UUID],
        before_state: dict[str, Any],
        result_memory_ids: list[UUID] | None = None,
        after_state: dict[str, Any] | None = None,
        reasoning: str | None = None,
    ) -> DreamAction:
        """
        Record an action in the dream journal.

        Updates session metrics based on action type.
        """
        action = DreamAction(
            session_id=dream_session.id,
            action_type=action_type,
            phase=phase,
            source_memory_ids=source_memory_ids,
            result_memory_ids=result_memory_ids,
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )
        session.add(action)
        session.flush()

        # Update session metrics based on action type
        if action_type == DreamActionType.MERGE:
            dream_session.memories_created += 1
            dream_session.memories_modified += len(source_memory_ids)
        elif action_type == DreamActionType.SPLIT:
            dream_session.memories_created += len(result_memory_ids or [])
            dream_session.memories_modified += 1
        elif action_type == DreamActionType.UPDATE:
            dream_session.memories_modified += 1
        elif action_type == DreamActionType.ARCHIVE:
            dream_session.memories_archived += 1
        elif action_type == DreamActionType.DELETE:
            dream_session.memories_deleted += 1

        session.flush()
        return action

    # ─────────────────────────────────────────────────────────────
    # Memory Operations (with audit trail)
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def merge_memories(
        session: Session,
        dream_session: DreamSession,
        source_memory_ids: list[UUID],
        merged_summary: str,
        merged_importance: float,
        merged_confidence: float,
        reasoning: str,
    ) -> Memory:
        """
        Merge multiple memories into one.

        Creates new memory with merged_from provenance in meta.
        Soft-deletes originals (MemoryEvent links preserved).

        Args:
            session: Database session
            dream_session: Parent dream session
            source_memory_ids: IDs of memories to merge
            merged_summary: LLM-generated unified summary
            merged_importance: Combined importance score
            merged_confidence: Combined confidence score
            reasoning: LLM explanation for the merge

        Returns:
            Newly created merged Memory
        """
        # Fetch source memories
        sources = [session.get(Memory, mid) for mid in source_memory_ids]
        sources = [s for s in sources if s is not None and not s.is_deleted]

        if len(sources) < 2:
            raise ValueError("Need at least 2 non-deleted memories to merge")

        # Verify all from same Anima
        anima_ids = {s.anima_id for s in sources}
        if len(anima_ids) > 1:
            raise ValueError("Cannot merge memories from different Animas")

        # Snapshot before state
        before_state = {
            "memories": [DreamerOperations._snapshot_memory(m) for m in sources]
        }

        # Calculate merged time span (earliest start, latest end)
        time_starts = [m.time_start for m in sources if m.time_start]
        time_ends = [m.time_end or m.time_start for m in sources if m.time_start]

        merged = Memory(
            anima_id=sources[0].anima_id,
            summary=merged_summary,
            # Concatenate content if available
            content="\n\n---\n\n".join(
                m.content for m in sources if m.content
            ) or None,
            importance=merged_importance,
            confidence=merged_confidence,
            state=MemoryState.ACTIVE,
            time_start=min(time_starts) if time_starts else None,
            time_end=max(time_ends) if time_ends else None,
            meta={"merged_from": [str(m.id) for m in sources]},
        )
        session.add(merged)
        session.flush()
        session.refresh(merged)

        # Soft-delete originals (preserves MemoryEvent links for provenance)
        for source in sources:
            source.is_deleted = True
        session.flush()

        # Snapshot after state
        after_state = {"memories": [DreamerOperations._snapshot_memory(merged)]}

        # Record action
        DreamerOperations._record_action(
            session,
            dream_session=dream_session,
            action_type=DreamActionType.MERGE,
            phase=DreamPhase.DEEP_SLEEP,
            source_memory_ids=source_memory_ids,
            result_memory_ids=[merged.id],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        return merged

    @staticmethod
    def split_memory(
        session: Session,
        dream_session: DreamSession,
        source_memory_id: UUID,
        split_summaries: list[str],
        reasoning: str,
    ) -> list[Memory]:
        """
        Split one memory into multiple distinct memories.

        Creates new memories with split_from provenance in meta.
        Soft-deletes original (MemoryEvent links preserved).

        Args:
            session: Database session
            dream_session: Parent dream session
            source_memory_id: ID of memory to split
            split_summaries: LLM-generated summaries for each split
            reasoning: LLM explanation for the split

        Returns:
            List of newly created Memory objects
        """
        source = session.get(Memory, source_memory_id)
        if not source:
            raise ValueError(f"Memory {source_memory_id} not found")
        if source.is_deleted:
            raise ValueError(f"Memory {source_memory_id} is already deleted")

        if len(split_summaries) < 2:
            raise ValueError("Need at least 2 summaries to split a memory")

        before_state = {"memories": [DreamerOperations._snapshot_memory(source)]}

        # Create split memories
        new_memories: list[Memory] = []
        for summary in split_summaries:
            new_mem = Memory(
                anima_id=source.anima_id,
                summary=summary,
                # Don't copy content — splits are about conceptual separation
                content=None,
                importance=source.importance,
                confidence=source.confidence,
                state=MemoryState.ACTIVE,
                time_start=source.time_start,
                time_end=source.time_end,
                meta={"split_from": str(source.id)},
            )
            session.add(new_mem)
            new_memories.append(new_mem)

        session.flush()
        for m in new_memories:
            session.refresh(m)

        # Soft-delete original
        source.is_deleted = True
        session.flush()

        after_state = {
            "memories": [DreamerOperations._snapshot_memory(m) for m in new_memories]
        }

        DreamerOperations._record_action(
            session,
            dream_session=dream_session,
            action_type=DreamActionType.SPLIT,
            phase=DreamPhase.DEEP_SLEEP,
            source_memory_ids=[source_memory_id],
            result_memory_ids=[m.id for m in new_memories],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        return new_memories

    @staticmethod
    def update_memory(
        session: Session,
        dream_session: DreamSession,
        memory_id: UUID,
        updates: dict[str, Any],
        phase: DreamPhase,
        reasoning: str | None = None,
    ) -> Memory:
        """
        Update a memory's fields, recording the change.

        Args:
            session: Database session
            dream_session: Parent dream session
            memory_id: ID of memory to update
            updates: Dict of field names to new values
            phase: LIGHT_SLEEP (algorithmic) or DEEP_SLEEP (LLM)
            reasoning: LLM explanation (None for algorithmic updates)

        Returns:
            Updated Memory
        """
        memory = session.get(Memory, memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.is_deleted:
            raise ValueError(f"Memory {memory_id} is deleted")

        before_state = {"memories": [DreamerOperations._snapshot_memory(memory)]}

        # Apply updates
        allowed_fields = {
            "summary", "content", "importance", "confidence",
            "decay_score", "recency_score", "state", "meta",
        }
        for key, value in updates.items():
            if key in allowed_fields and hasattr(memory, key):
                setattr(memory, key, value)

        session.flush()
        session.refresh(memory)

        after_state = {"memories": [DreamerOperations._snapshot_memory(memory)]}

        DreamerOperations._record_action(
            session,
            dream_session=dream_session,
            action_type=DreamActionType.UPDATE,
            phase=phase,
            source_memory_ids=[memory_id],
            result_memory_ids=[memory_id],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        return memory

    @staticmethod
    def archive_memory(
        session: Session,
        dream_session: DreamSession,
        memory_id: UUID,
        new_state: MemoryState,
        phase: DreamPhase,
        reasoning: str | None = None,
    ) -> Memory:
        """
        Transition a memory to DECAYING or ARCHIVED state.

        Args:
            session: Database session
            dream_session: Parent dream session
            memory_id: ID of memory to archive
            new_state: DECAYING or ARCHIVED
            phase: LIGHT_SLEEP (algorithmic) or DEEP_SLEEP (LLM)
            reasoning: LLM explanation (None for algorithmic transitions)

        Returns:
            Updated Memory with new state
        """
        if new_state not in (MemoryState.DECAYING, MemoryState.ARCHIVED):
            raise ValueError(f"Invalid archive state: {new_state}")

        memory = session.get(Memory, memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.is_deleted:
            raise ValueError(f"Memory {memory_id} is deleted")

        before_state = {"memories": [DreamerOperations._snapshot_memory(memory)]}

        memory.state = new_state
        session.flush()
        session.refresh(memory)

        after_state = {"memories": [DreamerOperations._snapshot_memory(memory)]}

        DreamerOperations._record_action(
            session,
            dream_session=dream_session,
            action_type=DreamActionType.ARCHIVE,
            phase=phase,
            source_memory_ids=[memory_id],
            result_memory_ids=[memory_id],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        return memory

    @staticmethod
    def delete_memory(
        session: Session,
        dream_session: DreamSession,
        memory_id: UUID,
        phase: DreamPhase,
        reasoning: str,
    ) -> None:
        """
        Soft-delete a memory as noise.

        Args:
            session: Database session
            dream_session: Parent dream session
            memory_id: ID of memory to delete
            phase: LIGHT_SLEEP (algorithmic) or DEEP_SLEEP (LLM)
            reasoning: Explanation for deletion (required)
        """
        memory = session.get(Memory, memory_id)
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.is_deleted:
            return  # Already deleted, no-op

        before_state = {"memories": [DreamerOperations._snapshot_memory(memory)]}

        memory.is_deleted = True
        session.flush()

        DreamerOperations._record_action(
            session,
            dream_session=dream_session,
            action_type=DreamActionType.DELETE,
            phase=phase,
            source_memory_ids=[memory_id],
            result_memory_ids=None,
            before_state=before_state,
            after_state=None,
            reasoning=reasoning,
        )
