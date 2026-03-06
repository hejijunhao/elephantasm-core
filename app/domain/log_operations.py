"""Domain operations for unified activity logs.

Aggregates entries from 8 tables into a single chronological timeline.
Static methods, sync session-based, no commits.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlmodel import Session

from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.dreams import DreamSession, DreamAction
from app.models.database.memory_pack import MemoryPack
from app.models.database.knowledge import Knowledge
from app.models.database.identity_audit_log import IdentityAuditLog
from app.models.database.knowledge_audit_log import KnowledgeAuditLog
from app.models.database.identity import Identity
from app.models.dto.log_entry import LogEntry, LogEntityType, LogsResponse, LogStats


class LogOperations:
    """Unified activity log queries. Static methods, sync."""

    @staticmethod
    def get_logs(
        session: Session,
        anima_id: UUID,
        limit: int = 50,
        offset: int = 0,
        entity_types: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> LogsResponse:
        """Fetch merged, sorted log entries from all entity tables."""
        type_set = set(entity_types) if entity_types else None
        fetch_limit = limit + offset + 1  # overfetch for merge-sort

        all_entries: list[LogEntry] = []

        if not type_set or "event" in type_set:
            all_entries.extend(
                LogOperations._fetch_events(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "memory" in type_set:
            all_entries.extend(
                LogOperations._fetch_memories(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "dream_session" in type_set:
            all_entries.extend(
                LogOperations._fetch_dream_sessions(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "dream_action" in type_set:
            all_entries.extend(
                LogOperations._fetch_dream_actions(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "memory_pack" in type_set:
            all_entries.extend(
                LogOperations._fetch_memory_packs(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "knowledge" in type_set:
            all_entries.extend(
                LogOperations._fetch_knowledge(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "identity_audit" in type_set:
            all_entries.extend(
                LogOperations._fetch_identity_audits(session, anima_id, fetch_limit, since, until)
            )
        if not type_set or "knowledge_audit" in type_set:
            all_entries.extend(
                LogOperations._fetch_knowledge_audits(session, anima_id, fetch_limit, since, until)
            )

        # Sort all entries by timestamp DESC
        all_entries.sort(key=lambda e: e.timestamp, reverse=True)

        has_more = len(all_entries) > offset + limit
        sliced = all_entries[offset : offset + limit]

        # Total is approximate (sum of overfetched); use stats for exact count
        total = len(all_entries) if not has_more else offset + limit + 1

        return LogsResponse(
            entries=sliced,
            total=total,
            has_more=has_more,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def get_stats(
        session: Session,
        anima_id: UUID,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> LogStats:
        """Count entries per type."""
        def _count(stmt):
            return session.execute(stmt).scalar_one()

        def _date_filter(col, since, until):
            filters = []
            if since:
                filters.append(col >= since)
            if until:
                filters.append(col <= until)
            return filters

        # Events
        q = select(func.count()).select_from(Event).where(
            Event.anima_id == anima_id, Event.is_deleted == False  # noqa: E712
        )
        for f in _date_filter(Event.occurred_at, since, until):
            q = q.where(f)
        event_count = _count(q)

        # Memories
        q = select(func.count()).select_from(Memory).where(
            Memory.anima_id == anima_id, Memory.is_deleted == False  # noqa: E712
        )
        for f in _date_filter(Memory.created_at, since, until):
            q = q.where(f)
        memory_count = _count(q)

        # Dream sessions
        q = select(func.count()).select_from(DreamSession).where(
            DreamSession.anima_id == anima_id
        )
        for f in _date_filter(DreamSession.started_at, since, until):
            q = q.where(f)
        dream_session_count = _count(q)

        # Dream actions (JOIN dream_sessions)
        q = (
            select(func.count())
            .select_from(DreamAction)
            .join(DreamSession, DreamAction.session_id == DreamSession.id)
            .where(DreamSession.anima_id == anima_id)
        )
        for f in _date_filter(DreamAction.created_at, since, until):
            q = q.where(f)
        dream_action_count = _count(q)

        # Memory packs
        q = select(func.count()).select_from(MemoryPack).where(
            MemoryPack.anima_id == anima_id
        )
        for f in _date_filter(MemoryPack.compiled_at, since, until):
            q = q.where(f)
        memory_pack_count = _count(q)

        # Knowledge
        q = select(func.count()).select_from(Knowledge).where(
            Knowledge.anima_id == anima_id, Knowledge.is_deleted == False  # noqa: E712
        )
        for f in _date_filter(Knowledge.created_at, since, until):
            q = q.where(f)
        knowledge_count = _count(q)

        # Identity audit (JOIN identities)
        q = (
            select(func.count())
            .select_from(IdentityAuditLog)
            .join(Identity, IdentityAuditLog.identity_id == Identity.id)
            .where(Identity.anima_id == anima_id)
        )
        for f in _date_filter(IdentityAuditLog.created_at, since, until):
            q = q.where(f)
        identity_audit_count = _count(q)

        # Knowledge audit (JOIN knowledge)
        q = (
            select(func.count())
            .select_from(KnowledgeAuditLog)
            .join(Knowledge, KnowledgeAuditLog.knowledge_id == Knowledge.id)
            .where(Knowledge.anima_id == anima_id)
        )
        for f in _date_filter(KnowledgeAuditLog.created_at, since, until):
            q = q.where(f)
        knowledge_audit_count = _count(q)

        total = (
            event_count + memory_count + dream_session_count + dream_action_count
            + memory_pack_count + knowledge_count + identity_audit_count + knowledge_audit_count
        )

        return LogStats(
            total=total,
            event=event_count,
            memory=memory_count,
            dream_session=dream_session_count,
            dream_action=dream_action_count,
            memory_pack=memory_pack_count,
            knowledge=knowledge_count,
            identity_audit=identity_audit_count,
            knowledge_audit=knowledge_audit_count,
        )

    # ── Private fetchers ──────────────────────────────────────────────

    @staticmethod
    def _fetch_events(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(Event)
            .where(Event.anima_id == anima_id, Event.is_deleted == False)  # noqa: E712
            .order_by(Event.occurred_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(Event.occurred_at >= since)
        if until:
            q = q.where(Event.occurred_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.EVENT,
                timestamp=r.occurred_at,
                title=f"Event: {r.event_type}",
                summary=(r.summary or (r.content[:120] if r.content else None)),
                icon="message",
                color="cyan",
                entity_id=r.id,
                anima_id=r.anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_memories(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(Memory)
            .where(Memory.anima_id == anima_id, Memory.is_deleted == False)  # noqa: E712
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(Memory.created_at >= since)
        if until:
            q = q.where(Memory.created_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.MEMORY,
                timestamp=r.created_at,
                title=f"Memory: {r.state.value if r.state else 'new'}",
                summary=(r.summary or (r.content[:120] if r.content else None)),
                icon="brain",
                color="blue",
                entity_id=r.id,
                anima_id=r.anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_dream_sessions(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(DreamSession)
            .where(DreamSession.anima_id == anima_id)
            .order_by(DreamSession.started_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(DreamSession.started_at >= since)
        if until:
            q = q.where(DreamSession.started_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.DREAM_SESSION,
                timestamp=r.started_at,
                title=f"Dream: {r.status.value}",
                summary=r.summary,
                icon="moon",
                color="purple",
                entity_id=r.id,
                anima_id=r.anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_dream_actions(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(DreamAction)
            .join(DreamSession, DreamAction.session_id == DreamSession.id)
            .where(DreamSession.anima_id == anima_id)
            .order_by(DreamAction.created_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(DreamAction.created_at >= since)
        if until:
            q = q.where(DreamAction.created_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.DREAM_ACTION,
                timestamp=r.created_at,
                title=f"Dream Action: {r.action_type.value}",
                summary=r.reasoning,
                icon="sparkles",
                color="violet",
                entity_id=r.id,
                anima_id=anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_memory_packs(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(MemoryPack)
            .where(MemoryPack.anima_id == anima_id)
            .order_by(MemoryPack.compiled_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(MemoryPack.compiled_at >= since)
        if until:
            q = q.where(MemoryPack.compiled_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.MEMORY_PACK,
                timestamp=r.compiled_at,
                title="Pack compiled",
                summary=f"{r.token_count} tokens, {r.session_memory_count + r.long_term_memory_count + r.knowledge_count} items",
                icon="package",
                color="orange",
                entity_id=r.id,
                anima_id=r.anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_knowledge(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(Knowledge)
            .where(Knowledge.anima_id == anima_id, Knowledge.is_deleted == False)  # noqa: E712
            .order_by(Knowledge.created_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(Knowledge.created_at >= since)
        if until:
            q = q.where(Knowledge.created_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.KNOWLEDGE,
                timestamp=r.created_at,
                title=f"Knowledge: {r.knowledge_type.value}",
                summary=(r.summary or (r.content[:120] if r.content else None)),
                icon="lightbulb",
                color="amber",
                entity_id=r.id,
                anima_id=r.anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_identity_audits(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(IdentityAuditLog)
            .join(Identity, IdentityAuditLog.identity_id == Identity.id)
            .where(Identity.anima_id == anima_id)
            .order_by(IdentityAuditLog.created_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(IdentityAuditLog.created_at >= since)
        if until:
            q = q.where(IdentityAuditLog.created_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.IDENTITY_AUDIT,
                timestamp=r.created_at,
                title=f"Identity: {r.action.value}",
                summary=r.change_summary,
                icon="fingerprint",
                color="rose",
                entity_id=r.id,
                anima_id=anima_id,
            )
            for r in rows
        ]

    @staticmethod
    def _fetch_knowledge_audits(
        session: Session, anima_id: UUID, limit: int,
        since: Optional[datetime], until: Optional[datetime],
    ) -> list[LogEntry]:
        q = (
            select(KnowledgeAuditLog)
            .join(Knowledge, KnowledgeAuditLog.knowledge_id == Knowledge.id)
            .where(Knowledge.anima_id == anima_id)
            .order_by(KnowledgeAuditLog.created_at.desc())
            .limit(limit)
        )
        if since:
            q = q.where(KnowledgeAuditLog.created_at >= since)
        if until:
            q = q.where(KnowledgeAuditLog.created_at <= until)

        rows = session.execute(q).scalars().all()
        return [
            LogEntry(
                id=r.id,
                entity_type=LogEntityType.KNOWLEDGE_AUDIT,
                timestamp=r.created_at,
                title=f"Knowledge Audit: {r.action.value}",
                summary=r.change_summary,
                icon="scroll",
                color="teal",
                entity_id=r.id,
                anima_id=anima_id,
            )
            for r in rows
        ]
