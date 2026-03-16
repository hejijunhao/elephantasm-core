"""
Meditator Domain Operations

All meditation-related CRUD operations with audit trail.
Every knowledge mutation records a MeditationAction for provenance,
plus a KnowledgeAuditLog entry for the existing audit system.

Pattern: Static methods, sync operations, session passed explicitly.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlmodel import Session

import logging

from app.domain.exceptions import (
    DomainValidationError,
    EntityDeletedError,
    EntityNotFoundError,
)

logger = logging.getLogger(__name__)
from app.models.database.knowledge import (
    AuditAction,
    Knowledge,
    KnowledgeType,
    SourceType,
)
from app.models.database.knowledge_audit_log import AuditLogCreate
from app.models.database.meditations import (
    MeditationAction,
    MeditationActionType,
    MeditationPhase,
    MeditationSession,
    MeditationStatus,
    MeditationTriggerType,
)
from app.models.database.synthesis_config import SynthesisConfig


class MeditatorOperations:
    """Static methods for meditation operations with audit trail."""

    # ─────────────────────────────────────────────────────────────
    # Session Management
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def create_session(
        session: Session,
        anima_id: UUID,
        trigger_type: MeditationTriggerType,
        triggered_by: UUID | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> MeditationSession:
        """Create a new meditation session in RUNNING state."""
        meditation = MeditationSession(
            anima_id=anima_id,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            config_snapshot=config_snapshot or {},
        )
        session.add(meditation)
        session.flush()
        session.refresh(meditation)
        return meditation

    @staticmethod
    def complete_session(
        session: Session,
        session_id: UUID,
        summary: str,
    ) -> MeditationSession:
        """Mark meditation session as COMPLETED."""
        meditation = session.get(MeditationSession, session_id)
        if not meditation:
            raise EntityNotFoundError("MeditationSession", session_id)

        meditation.status = MeditationStatus.COMPLETED
        meditation.completed_at = datetime.now(timezone.utc)
        meditation.summary = summary
        session.flush()
        session.refresh(meditation)
        return meditation

    @staticmethod
    def fail_session(
        session: Session,
        session_id: UUID,
        error_message: str,
    ) -> MeditationSession:
        """Mark meditation session as FAILED, retaining partial actions.
        No-op if session is already COMPLETED or FAILED (prevents overwrite)."""
        meditation = session.get(MeditationSession, session_id)
        if not meditation:
            raise EntityNotFoundError("MeditationSession", session_id)

        if meditation.status != MeditationStatus.RUNNING:
            logger.warning(
                f"Skipping fail_session for {session_id} — already {meditation.status.value}"
            )
            return meditation

        action_count = session.scalar(
            select(func.count(MeditationAction.id)).where(
                MeditationAction.session_id == session_id
            )
        )

        meditation.status = MeditationStatus.FAILED
        meditation.completed_at = datetime.now(timezone.utc)
        meditation.error_message = f"Failed after {action_count} actions: {error_message}"
        session.flush()
        session.refresh(meditation)
        return meditation

    @staticmethod
    def cancel_session(
        session: Session,
        session_id: UUID,
        cancelled_by: UUID | None = None,
    ) -> MeditationSession:
        """Cancel a running meditation session. Only RUNNING sessions can be cancelled."""
        meditation = session.get(MeditationSession, session_id)
        if not meditation:
            raise EntityNotFoundError("MeditationSession", session_id)

        if meditation.status != MeditationStatus.RUNNING:
            raise DomainValidationError(
                f"Cannot cancel session with status {meditation.status.value}. "
                "Only RUNNING sessions can be cancelled."
            )

        meditation.status = MeditationStatus.FAILED
        meditation.completed_at = datetime.now(timezone.utc)
        meditation.error_message = (
            f"Cancelled by user {cancelled_by}" if cancelled_by
            else "Cancelled by user"
        )
        session.flush()
        session.refresh(meditation)
        return meditation

    @staticmethod
    def get_last_session(
        session: Session,
        anima_id: UUID,
        completed_only: bool = True,
    ) -> MeditationSession | None:
        """Get the most recent meditation session for an Anima."""
        query = select(MeditationSession).where(MeditationSession.anima_id == anima_id)

        if completed_only:
            query = query.where(MeditationSession.status == MeditationStatus.COMPLETED)

        query = query.order_by(MeditationSession.started_at.desc()).limit(1)
        return session.execute(query).scalars().first()

    @staticmethod
    def has_running_session(session: Session, anima_id: UUID) -> bool:
        """Check if Anima has a meditation currently in progress."""
        result = session.execute(
            select(MeditationSession.id)
            .where(MeditationSession.anima_id == anima_id)
            .where(MeditationSession.status == MeditationStatus.RUNNING)
            .limit(1)
        ).scalars().first()
        return result is not None

    # ─────────────────────────────────────────────────────────────
    # Counter Management
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def increment_synth_count(
        session: Session, anima_id: UUID, count: int = 1
    ) -> tuple[int, int]:
        """
        Atomically increment knowledge_synth_count on SynthesisConfig.
        Returns (new_count, threshold). Uses SQL-level increment to avoid race conditions.
        """
        from sqlalchemy import update

        result = session.execute(
            update(SynthesisConfig)
            .where(SynthesisConfig.anima_id == anima_id)
            .values(knowledge_synth_count=SynthesisConfig.knowledge_synth_count + count)
            .returning(
                SynthesisConfig.knowledge_synth_count,
                SynthesisConfig.meditation_threshold,
            )
        )
        row = result.first()
        if not row:
            return (0, 10)

        session.flush()
        return (row[0], row[1])

    @staticmethod
    def reset_synth_count(session: Session, anima_id: UUID) -> None:
        """Reset knowledge_synth_count to 0 after meditation fires.
        Uses SQL-level UPDATE to avoid read-modify-write race with concurrent increments."""
        from sqlalchemy import update

        session.execute(
            update(SynthesisConfig)
            .where(SynthesisConfig.anima_id == anima_id)
            .values(knowledge_synth_count=0)
        )
        session.flush()

    @staticmethod
    def get_synth_count(session: Session, anima_id: UUID) -> tuple[int, int]:
        """
        Get (count, threshold) for meditation trigger check.
        Returns (0, 10) if no config exists.
        """
        config = session.execute(
            select(SynthesisConfig).where(SynthesisConfig.anima_id == anima_id)
        ).scalars().first()

        if not config:
            return (0, 10)

        return (config.knowledge_synth_count, config.meditation_threshold)

    # ─────────────────────────────────────────────────────────────
    # Snapshot Helpers
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _snapshot_knowledge(knowledge: Knowledge) -> dict[str, Any]:
        """Create a JSON snapshot of a knowledge item for audit trail."""
        return {
            "id": str(knowledge.id),
            "knowledge_type": knowledge.knowledge_type.value if knowledge.knowledge_type else None,
            "topic": knowledge.topic,
            "content": knowledge.content,
            "summary": knowledge.summary,
            "confidence": knowledge.confidence,
            "source_type": knowledge.source_type.value if knowledge.source_type else None,
            "is_deleted": knowledge.is_deleted,
        }

    @staticmethod
    def _record_action(
        session: Session,
        meditation_session: MeditationSession,
        action_type: MeditationActionType,
        phase: MeditationPhase,
        source_knowledge_ids: list[UUID],
        before_state: dict[str, Any],
        result_knowledge_ids: list[UUID] | None = None,
        after_state: dict[str, Any] | None = None,
        reasoning: str | None = None,
    ) -> MeditationAction:
        """Record an action in the meditation journal. Updates session metrics."""
        action = MeditationAction(
            session_id=meditation_session.id,
            action_type=action_type,
            phase=phase,
            source_knowledge_ids=source_knowledge_ids,
            result_knowledge_ids=result_knowledge_ids,
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )
        session.add(action)
        session.flush()

        # Update session metrics
        if action_type == MeditationActionType.MERGE:
            meditation_session.knowledge_created += len(result_knowledge_ids) if result_knowledge_ids else 1
            meditation_session.knowledge_modified += len(source_knowledge_ids)
        elif action_type == MeditationActionType.SPLIT:
            meditation_session.knowledge_created += len(result_knowledge_ids or [])
            meditation_session.knowledge_modified += 1
        elif action_type in (MeditationActionType.UPDATE, MeditationActionType.RECLASSIFY):
            meditation_session.knowledge_modified += 1
        elif action_type == MeditationActionType.DELETE:
            meditation_session.knowledge_deleted += 1

        session.flush()
        return action

    @staticmethod
    def _create_audit_log(
        session: Session,
        knowledge_id: UUID,
        action: AuditAction,
        before_state: dict | None,
        after_state: dict,
        change_summary: str | None = None,
    ) -> None:
        """Create a KnowledgeAuditLog entry linking Meditator actions to existing audit trail."""
        from app.domain.knowledge_audit_operations import KnowledgeAuditOperations

        KnowledgeAuditOperations.create(
            session,
            AuditLogCreate(
                knowledge_id=knowledge_id,
                action=action,
                before_state=before_state,
                after_state=after_state,
                change_summary=change_summary,
                triggered_by="meditator",
            ),
        )

    # ─────────────────────────────────────────────────────────────
    # Knowledge Operations (with audit trail)
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def merge_knowledge(
        session: Session,
        meditation_session: MeditationSession,
        source_knowledge_ids: list[UUID],
        merged_definitions: list[dict[str, Any]],
        reasoning: str,
    ) -> list[Knowledge]:
        """
        Merge N source knowledge items into M new items.

        Creates new Knowledge with merged_from provenance in meta.
        Soft-deletes originals. Also writes KnowledgeAuditLog entries.

        Args:
            merged_definitions: List of dicts, each with:
                - content (str): merged content
                - summary (str, optional): one-liner
                - knowledge_type (str): KnowledgeType value
                - topic (str, optional): topic grouping
                - confidence (float, optional): 0.0-1.0
                - source_type (str, optional): SourceType value
        """
        if not merged_definitions:
            raise DomainValidationError("Need at least 1 merged definition")

        sources = [session.get(Knowledge, kid) for kid in source_knowledge_ids]
        missing = [
            str(kid) for kid, s in zip(source_knowledge_ids, sources)
            if s is None or s.is_deleted
        ]
        if missing:
            raise DomainValidationError(
                f"Knowledge items not found or deleted: {', '.join(missing)}"
            )
        sources = [s for s in sources if s is not None]

        if len(sources) < 2:
            raise DomainValidationError("Need at least 2 non-deleted knowledge items to merge")

        anima_ids = {s.anima_id for s in sources}
        if len(anima_ids) > 1:
            raise DomainValidationError("Cannot merge knowledge from different Animas")

        before_state = {
            "knowledge": [MeditatorOperations._snapshot_knowledge(k) for k in sources]
        }
        # Capture per-source snapshots before mutation for audit logs
        source_snapshots = {
            s.id: MeditatorOperations._snapshot_knowledge(s) for s in sources
        }

        # Create M new knowledge items
        new_items: list[Knowledge] = []
        all_source_ids = [str(k.id) for k in sources]

        for defn in merged_definitions:
            # Resolve knowledge_type — use provided or inherit from first source
            ktype_str = defn.get("knowledge_type")
            ktype = KnowledgeType(ktype_str) if ktype_str else sources[0].knowledge_type

            stype_str = defn.get("source_type")
            stype = SourceType(stype_str) if stype_str else sources[0].source_type

            merged = Knowledge(
                anima_id=sources[0].anima_id,
                knowledge_type=ktype,
                topic=defn.get("topic", sources[0].topic),
                content=defn["content"],
                summary=defn.get("summary"),
                confidence=defn.get("confidence", max(
                    (s.confidence for s in sources if s.confidence is not None),
                    default=0.5,
                )),
                source_type=stype,
            )
            # Store provenance in model's meta-like approach (no meta column on Knowledge,
            # so we track via audit log instead)
            session.add(merged)
            new_items.append(merged)

        session.flush()
        for k in new_items:
            session.refresh(k)

        # Soft-delete originals
        for source in sources:
            source.is_deleted = True
        session.flush()

        after_state = {
            "knowledge": [MeditatorOperations._snapshot_knowledge(k) for k in new_items]
        }

        # Record meditation action
        MeditatorOperations._record_action(
            session,
            meditation_session=meditation_session,
            action_type=MeditationActionType.MERGE,
            phase=MeditationPhase.CONTEMPLATION,
            source_knowledge_ids=source_knowledge_ids,
            result_knowledge_ids=[k.id for k in new_items],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        # Write KnowledgeAuditLog for each new item
        for new_k in new_items:
            MeditatorOperations._create_audit_log(
                session,
                knowledge_id=new_k.id,
                action=AuditAction.CREATE,
                before_state=None,
                after_state=MeditatorOperations._snapshot_knowledge(new_k),
                change_summary=f"Created by meditator merge from {len(sources)} sources: {', '.join(all_source_ids[:3])}",
            )

        # Audit log for deleted originals (use pre-mutation snapshots)
        for source in sources:
            MeditatorOperations._create_audit_log(
                session,
                knowledge_id=source.id,
                action=AuditAction.DELETE,
                before_state=source_snapshots[source.id],
                after_state={"is_deleted": True},
                change_summary=f"Soft-deleted by meditator merge into {len(new_items)} item(s)",
            )

        return new_items

    @staticmethod
    def split_knowledge(
        session: Session,
        meditation_session: MeditationSession,
        source_knowledge_id: UUID,
        split_definitions: list[dict[str, Any]],
        reasoning: str,
    ) -> list[Knowledge]:
        """
        Split one knowledge item into multiple distinct items.

        Args:
            split_definitions: List of dicts, each with:
                - content (str): split content
                - summary (str, optional)
                - knowledge_type (str, optional): defaults to source's type
                - topic (str, optional): defaults to source's topic
                - confidence (float, optional): defaults to source's confidence
        """
        source = session.get(Knowledge, source_knowledge_id)
        if not source:
            raise EntityNotFoundError("Knowledge", source_knowledge_id)
        if source.is_deleted:
            raise EntityDeletedError("Knowledge", source_knowledge_id)

        if len(split_definitions) < 2:
            raise DomainValidationError("Need at least 2 definitions to split knowledge")

        before_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(source)]}
        source_snapshot = MeditatorOperations._snapshot_knowledge(source)

        new_items: list[Knowledge] = []
        for defn in split_definitions:
            ktype_str = defn.get("knowledge_type")
            ktype = KnowledgeType(ktype_str) if ktype_str else source.knowledge_type

            new_k = Knowledge(
                anima_id=source.anima_id,
                knowledge_type=ktype,
                topic=defn.get("topic", source.topic),
                content=defn["content"],
                summary=defn.get("summary"),
                confidence=defn.get("confidence", source.confidence),
                source_type=source.source_type,
            )
            session.add(new_k)
            new_items.append(new_k)

        session.flush()
        for k in new_items:
            session.refresh(k)

        # Soft-delete original
        source.is_deleted = True
        session.flush()

        after_state = {
            "knowledge": [MeditatorOperations._snapshot_knowledge(k) for k in new_items]
        }

        MeditatorOperations._record_action(
            session,
            meditation_session=meditation_session,
            action_type=MeditationActionType.SPLIT,
            phase=MeditationPhase.CONTEMPLATION,
            source_knowledge_ids=[source_knowledge_id],
            result_knowledge_ids=[k.id for k in new_items],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        # Audit logs
        for new_k in new_items:
            MeditatorOperations._create_audit_log(
                session,
                knowledge_id=new_k.id,
                action=AuditAction.CREATE,
                before_state=None,
                after_state=MeditatorOperations._snapshot_knowledge(new_k),
                change_summary=f"Created by meditator split from {source_knowledge_id}",
            )

        MeditatorOperations._create_audit_log(
            session,
            knowledge_id=source.id,
            action=AuditAction.DELETE,
            before_state=source_snapshot,
            after_state={"is_deleted": True},
            change_summary=f"Soft-deleted by meditator split into {len(new_items)} item(s)",
        )

        return new_items

    @staticmethod
    def update_knowledge(
        session: Session,
        meditation_session: MeditationSession,
        knowledge_id: UUID,
        updates: dict[str, Any],
        phase: MeditationPhase,
        reasoning: str | None = None,
    ) -> Knowledge:
        """
        Update a knowledge item's fields (content, summary, confidence).

        Args:
            updates: Dict of field names to new values.
                     Allowed: content, summary, confidence.
        """
        knowledge = session.get(Knowledge, knowledge_id)
        if not knowledge:
            raise EntityNotFoundError("Knowledge", knowledge_id)
        if knowledge.is_deleted:
            raise EntityDeletedError("Knowledge", knowledge_id)

        before_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(knowledge)]}
        before_snapshot = MeditatorOperations._snapshot_knowledge(knowledge)

        allowed_fields = {"content", "summary", "confidence"}
        for key, value in updates.items():
            if key in allowed_fields and hasattr(knowledge, key):
                setattr(knowledge, key, value)

        knowledge.updated_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(knowledge)

        after_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(knowledge)]}

        MeditatorOperations._record_action(
            session,
            meditation_session=meditation_session,
            action_type=MeditationActionType.UPDATE,
            phase=phase,
            source_knowledge_ids=[knowledge_id],
            result_knowledge_ids=[knowledge_id],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        MeditatorOperations._create_audit_log(
            session,
            knowledge_id=knowledge_id,
            action=AuditAction.UPDATE,
            before_state=before_snapshot,
            after_state=MeditatorOperations._snapshot_knowledge(knowledge),
            change_summary=f"Updated by meditator: {', '.join(updates.keys())}",
        )

        return knowledge

    @staticmethod
    def reclassify_knowledge(
        session: Session,
        meditation_session: MeditationSession,
        knowledge_id: UUID,
        new_type: KnowledgeType | None = None,
        new_topic: str | None = None,
        reasoning: str | None = None,
    ) -> Knowledge:
        """
        Change knowledge_type and/or topic without altering content.
        Unique to Knowledge — Memories don't have type taxonomies.
        At least one of new_type or new_topic must be provided.
        """
        if new_type is None and new_topic is None:
            raise DomainValidationError("Must provide new_type or new_topic for reclassification")

        knowledge = session.get(Knowledge, knowledge_id)
        if not knowledge:
            raise EntityNotFoundError("Knowledge", knowledge_id)
        if knowledge.is_deleted:
            raise EntityDeletedError("Knowledge", knowledge_id)

        before_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(knowledge)]}
        before_snapshot = MeditatorOperations._snapshot_knowledge(knowledge)

        changes = []
        if new_type is not None and new_type != knowledge.knowledge_type:
            knowledge.knowledge_type = new_type
            changes.append(f"type→{new_type.value}")
        if new_topic is not None and new_topic != knowledge.topic:
            knowledge.topic = new_topic
            changes.append(f"topic→{new_topic}")

        if not changes:
            return knowledge  # No actual change, no-op

        knowledge.updated_at = datetime.now(timezone.utc)
        session.flush()
        session.refresh(knowledge)

        after_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(knowledge)]}

        MeditatorOperations._record_action(
            session,
            meditation_session=meditation_session,
            action_type=MeditationActionType.RECLASSIFY,
            phase=MeditationPhase.CONTEMPLATION,
            source_knowledge_ids=[knowledge_id],
            result_knowledge_ids=[knowledge_id],
            before_state=before_state,
            after_state=after_state,
            reasoning=reasoning,
        )

        MeditatorOperations._create_audit_log(
            session,
            knowledge_id=knowledge_id,
            action=AuditAction.UPDATE,
            before_state=before_snapshot,
            after_state=MeditatorOperations._snapshot_knowledge(knowledge),
            change_summary=f"Reclassified by meditator: {', '.join(changes)}",
        )

        return knowledge

    @staticmethod
    def delete_knowledge(
        session: Session,
        meditation_session: MeditationSession,
        knowledge_id: UUID,
        phase: MeditationPhase,
        reasoning: str,
    ) -> None:
        """Soft-delete a knowledge item as noise or superseded."""
        knowledge = session.get(Knowledge, knowledge_id)
        if not knowledge:
            raise EntityNotFoundError("Knowledge", knowledge_id)
        if knowledge.is_deleted:
            return  # Already deleted, no-op

        before_state = {"knowledge": [MeditatorOperations._snapshot_knowledge(knowledge)]}
        before_snapshot = MeditatorOperations._snapshot_knowledge(knowledge)

        knowledge.is_deleted = True
        knowledge.updated_at = datetime.now(timezone.utc)
        session.flush()

        MeditatorOperations._record_action(
            session,
            meditation_session=meditation_session,
            action_type=MeditationActionType.DELETE,
            phase=phase,
            source_knowledge_ids=[knowledge_id],
            result_knowledge_ids=None,
            before_state=before_state,
            after_state=None,
            reasoning=reasoning,
        )

        MeditatorOperations._create_audit_log(
            session,
            knowledge_id=knowledge_id,
            action=AuditAction.DELETE,
            before_state=before_snapshot,
            after_state={"is_deleted": True},
            change_summary=f"Deleted by meditator: {reasoning}",
        )
