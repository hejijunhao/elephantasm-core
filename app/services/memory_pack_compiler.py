"""
Memory Pack Compiler - Core Pack Assembly Service

Assembles memory packs for LLM context injection.
Combines 4 layers: Identity, Session Memories, Knowledge, Long-term Memories.

v1 Constraints:
- Synchronous (wait for full pack)
- Full injection every turn (no diffing)
- No token tracking (harness manages context)
- No LLM calls during retrieval
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID
from enum import Enum
import math

from sqlmodel import Session

from app.domain.memory_retrieval import MemoryRetrieval
from app.domain.knowledge_retrieval import KnowledgeRetrieval
from app.domain.identity_operations import IdentityOperations
from app.algos.mem_scoring import (
    compute_recency_score,
    compute_decay_score,
    compute_combined_score,
    ScoringWeights,
)
from app.algos.mem_scoring.combined import compute_knowledge_score
from app.services.embeddings import get_embedding_provider
from app.models.dto.retrieval import RetrievalConfig, TemporalContext
from app.models.database.memories import Memory
from app.models.database.knowledge import Knowledge


class RetrievalReason(str, Enum):
    """Why a memory was included in the pack."""

    SESSION_RECENCY = "session_recency"  # Recent, same session
    SEMANTIC_MATCH = "semantic_match"  # Query similarity
    HIGH_IMPORTANCE = "high_importance"  # Inherently important
    HYBRID = "hybrid"  # Multiple factors


@dataclass
class ScoredMemory:
    """Memory with computed retrieval score."""

    memory: Memory
    score: float
    retrieval_reason: RetrievalReason
    similarity: Optional[float] = None
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class ScoredKnowledge:
    """Knowledge with computed retrieval score."""

    knowledge: Knowledge
    score: float
    similarity: Optional[float] = None


@dataclass
class IdentitySummary:
    """Condensed identity for pack injection."""

    name: Optional[str]  # Anima name
    personality_type: Optional[str]
    communication_style: Optional[str]
    self_reflection: Optional[Dict[str, Any]]


@dataclass
class CompiledPack:
    """Compiled memory pack for LLM injection."""

    anima_id: UUID
    query: Optional[str]
    compiled_at: datetime
    token_count: int

    # Four layers + temporal awareness
    identity: Optional[IdentitySummary]
    temporal_context: Optional[TemporalContext]  # Bridges session gaps
    session_memories: List[ScoredMemory]
    knowledge: List[ScoredKnowledge]
    long_term_memories: List[ScoredMemory]

    config: RetrievalConfig

    def to_prompt_context(self) -> str:
        """Format pack as injectable prompt context."""
        from app.utils.memory_pack import format_identity_prose

        sections = []

        # Identity section (natural language prose)
        if self.identity:
            identity_prose = format_identity_prose(
                name=self.identity.name,
                personality_type=self.identity.personality_type,
                communication_style=self.identity.communication_style,
                self_reflection=self.identity.self_reflection,
            )
            if identity_prose:
                sections.append(f"## Your Identity\n{identity_prose}")

        # Temporal awareness (bridges session gaps)
        if self.temporal_context:
            sections.append(f"## Session Context\n{self.temporal_context.formatted}")

        # Session context (recent memories from this session)
        if self.session_memories:
            session_text = "\n".join(
                [f"- {m.memory.summary}" for m in self.session_memories]
            )
            sections.append(f"## Current Session\n{session_text}")

        # Knowledge section (semantic)
        if self.knowledge:
            knowledge_text = "\n".join(
                [
                    f"- [{k.knowledge.knowledge_type.value}] {k.knowledge.content}"
                    for k in self.knowledge
                ]
            )
            sections.append(f"## Relevant Knowledge\n{knowledge_text}")

        # Long-term memories section (semantic + scored)
        if self.long_term_memories:
            memories_text = "\n".join(
                [
                    f"- [{m.memory.time_start.strftime('%Y-%m-%d') if m.memory.time_start else 'Unknown'}] {m.memory.summary}"
                    for m in self.long_term_memories
                ]
            )
            sections.append(f"## Relevant Memories\n{memories_text}")

        return "\n\n".join(sections)


class MemoryPackCompiler:
    """
    Assembles memory packs for LLM context injection.

    v1: Synchronous, full injection, no token tracking.
    Retrieves 4 layers with distinct strategies per layer.
    """

    def __init__(self, session: Session):
        self.session = session
        self._embedding_provider = None

    # Default retention: keep last 100 packs per anima
    DEFAULT_RETENTION_COUNT = 100

    @property
    def embedding_provider(self):
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider()
        return self._embedding_provider

    def compile(
        self,
        config: RetrievalConfig,
        persist: bool = False,
        preset_name: Optional[str] = None,
    ) -> CompiledPack:
        """
        Compile a memory pack based on configuration.

        Steps:
        1. Retrieve identity (static fetch)
        2. Retrieve session memories (recency-based, no semantic)
        3. Retrieve knowledge (semantic search)
        4. Retrieve long-term memories (semantic + full scoring)
        5. Enforce token budget
        6. Package into CompiledPack
        7. Optionally persist to database

        Args:
            config: Retrieval configuration
            persist: Whether to persist pack to database
            preset_name: Optional preset name for persistence metadata
        """
        now = datetime.now(timezone.utc)
        weights = self._build_weights(config)

        # Get query embedding for semantic search
        query_embedding = None
        if config.query:
            query_embedding = self.embedding_provider.embed_text(config.query)

        # Layer 1: Identity (static fetch)
        identity = None
        if config.include_identity:
            identity = self._retrieve_identity(config.anima_id)

        # Layer 2: Session memories (recency-based, current session)
        session_memories = self._retrieve_session_memories(config, now)

        # Temporal awareness: If session is empty, provide context about last interaction
        temporal_context = None
        if (
            not session_memories
            and config.include_temporal_awareness
        ):
            temporal_context = MemoryRetrieval.get_temporal_context(
                self.session, config.anima_id
            )

        # Layer 3: Knowledge (semantic search)
        knowledge = self._retrieve_knowledge(config, query_embedding)

        # Layer 4: Long-term memories (semantic + full scoring)
        long_term_memories = self._retrieve_long_term_memories(
            config, query_embedding, weights, now
        )

        # Enforce token budget across all layers
        session_memories, knowledge, long_term_memories = self._enforce_token_budget(
            session_memories, knowledge, long_term_memories, identity, config.max_tokens
        )

        # Compute total tokens
        token_count = self._estimate_tokens(
            session_memories, knowledge, long_term_memories, identity
        )

        pack = CompiledPack(
            anima_id=config.anima_id,
            query=config.query,
            compiled_at=now,
            token_count=token_count,
            identity=identity,
            temporal_context=temporal_context,
            session_memories=session_memories,
            knowledge=knowledge,
            long_term_memories=long_term_memories,
            config=config,
        )

        # Persist if requested
        if persist:
            self._persist_pack(pack, config, preset_name)

        return pack

    def _retrieve_identity(self, anima_id: UUID) -> Optional[IdentitySummary]:
        """Layer 1: Static identity fetch."""
        from app.domain.anima_operations import AnimaOperations

        identity = IdentityOperations.get_by_anima_id(self.session, anima_id)
        if not identity:
            return None

        # Fetch Anima name
        anima = AnimaOperations.get_by_id(self.session, anima_id)
        anima_name = anima.name if anima else None

        return IdentitySummary(
            name=anima_name,
            personality_type=(
                identity.personality_type.value if identity.personality_type else None
            ),
            communication_style=identity.communication_style,
            self_reflection=identity.self_ or {},
        )

    def _retrieve_session_memories(
        self,
        config: RetrievalConfig,
        now: datetime,
    ) -> List[ScoredMemory]:
        """
        Layer 2: Session memories (recency-based, no semantic search).

        Retrieves memories from the current session, sorted by recency.
        These provide implicit "session context" — what we're discussing now.
        """
        session_cutoff = now - timedelta(hours=config.session_window_hours)

        # Get recent memories
        candidates = MemoryRetrieval.get_session_memories(
            self.session,
            anima_id=config.anima_id,
            session_cutoff=session_cutoff,
            limit=config.max_session_memories * 2,  # Over-fetch for filtering
        )

        scored = []
        for memory in candidates:
            # Use created_at for recency (timezone-aware)
            memory_time = memory.created_at
            if memory_time.tzinfo is None:
                memory_time = memory_time.replace(tzinfo=timezone.utc)

            recency = compute_recency_score(memory_time, now, half_life_days=1.0)

            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=recency,  # Session memories scored by recency only
                    retrieval_reason=RetrievalReason.SESSION_RECENCY,
                    similarity=None,
                    score_breakdown={"recency": recency},
                )
            )

        # Sort by recency (most recent first)
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: config.max_session_memories]

    def _retrieve_knowledge(
        self,
        config: RetrievalConfig,
        query_embedding: Optional[List[float]],
    ) -> List[ScoredKnowledge]:
        """
        Layer 3: Knowledge (semantic search).

        Retrieves knowledge items by semantic similarity to query.
        """
        if not query_embedding:
            # No query = no semantic search, return empty
            return []

        # Convert enum list for search
        knowledge_types = config.knowledge_types

        # Semantic search
        results = KnowledgeRetrieval.search_similar(
            self.session,
            anima_id=config.anima_id,
            query_embedding=query_embedding,
            limit=config.max_knowledge,
            threshold=config.similarity_threshold,
            knowledge_types=knowledge_types,
        )

        scored = []
        for knowledge, similarity in results:
            # Knowledge scoring: confidence + similarity (no recency/decay)
            score = compute_knowledge_score(knowledge.confidence, similarity)

            scored.append(
                ScoredKnowledge(
                    knowledge=knowledge,
                    score=score,
                    similarity=similarity,
                )
            )

        return scored  # Already sorted by similarity from search

    def _retrieve_long_term_memories(
        self,
        config: RetrievalConfig,
        query_embedding: Optional[List[float]],
        weights: ScoringWeights,
        now: datetime,
    ) -> List[ScoredMemory]:
        """
        Layer 4: Long-term memories (semantic + full scoring).

        Retrieves memories from outside current session using full
        scoring algorithm: importance, confidence, recency, decay, similarity.
        """
        if not query_embedding:
            # No query = no semantic search for long-term
            return []

        # Get memories older than session window
        session_cutoff = now - timedelta(hours=config.session_window_hours)

        # Get candidates with embeddings
        candidates = MemoryRetrieval.get_with_embeddings(
            self.session,
            anima_id=config.anima_id,
            states=config.memory_states,
            max_time=session_cutoff,
            min_importance=config.min_importance,
            limit=config.max_long_term_memories * 3,  # Over-fetch for filtering
        )

        scored = []
        for memory in candidates:
            if memory.embedding is None or len(memory.embedding) == 0:
                continue

            # Semantic similarity filter
            similarity = self._cosine_similarity(query_embedding, memory.embedding)
            if similarity < config.similarity_threshold:
                continue

            # Compute all scoring factors
            memory_time = memory.created_at
            if memory_time.tzinfo is None:
                memory_time = memory_time.replace(tzinfo=timezone.utc)

            recency = compute_recency_score(memory_time, now)

            last_accessed = memory.updated_at
            if last_accessed and last_accessed.tzinfo is None:
                last_accessed = last_accessed.replace(tzinfo=timezone.utc)

            decay = compute_decay_score(
                memory_time,
                last_accessed=last_accessed,
                access_count=0,  # TODO: Add access tracking
            )

            # Combined score
            score = compute_combined_score(
                importance=memory.importance,
                confidence=memory.confidence,
                recency_score=recency,
                decay_score=decay,
                similarity=similarity,
                weights=weights,
            )

            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=score,
                    retrieval_reason=RetrievalReason.HYBRID,
                    similarity=similarity,
                    score_breakdown={
                        "importance": memory.importance or 0.5,
                        "confidence": memory.confidence or 0.5,
                        "recency": recency,
                        "decay": decay,
                        "similarity": similarity,
                    },
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: config.max_long_term_memories]

    def _enforce_token_budget(
        self,
        session_memories: List[ScoredMemory],
        knowledge: List[ScoredKnowledge],
        long_term_memories: List[ScoredMemory],
        identity: Optional[IdentitySummary],
        max_tokens: int,
    ) -> tuple:
        """
        Trim content to fit token budget.

        Priority order: Identity > Session > Knowledge > Long-term
        """
        # Reserve tokens for identity (fixed cost)
        identity_tokens = 150 if identity else 0
        remaining = max_tokens - identity_tokens

        # Budget split: 25% session, 35% knowledge, 40% long-term
        session_budget = int(remaining * 0.25)
        knowledge_budget = int(remaining * 0.35)
        longterm_budget = int(remaining * 0.40)

        # Trim each layer
        trimmed_session = self._trim_memories_to_budget(session_memories, session_budget)
        trimmed_knowledge = self._trim_knowledge_to_budget(knowledge, knowledge_budget)
        trimmed_longterm = self._trim_memories_to_budget(
            long_term_memories, longterm_budget
        )

        return trimmed_session, trimmed_knowledge, trimmed_longterm

    def _trim_memories_to_budget(
        self,
        memories: List[ScoredMemory],
        budget: int,
    ) -> List[ScoredMemory]:
        """Trim memories to fit token budget."""
        trimmed = []
        tokens_used = 0
        for m in memories:
            est_tokens = len(m.memory.summary or "") // 4
            if tokens_used + est_tokens > budget:
                break
            trimmed.append(m)
            tokens_used += est_tokens
        return trimmed

    def _trim_knowledge_to_budget(
        self,
        knowledge: List[ScoredKnowledge],
        budget: int,
    ) -> List[ScoredKnowledge]:
        """Trim knowledge to fit token budget."""
        trimmed = []
        tokens_used = 0
        for k in knowledge:
            est_tokens = len(k.knowledge.content or "") // 4
            if tokens_used + est_tokens > budget:
                break
            trimmed.append(k)
            tokens_used += est_tokens
        return trimmed

    def _build_weights(self, config: RetrievalConfig) -> ScoringWeights:
        """Build scoring weights from config."""
        return ScoringWeights(
            importance=config.weight_importance,
            confidence=config.weight_confidence,
            recency=config.weight_recency,
            decay=config.weight_decay,
            similarity=config.weight_similarity,
        )

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _estimate_tokens(
        session: List[ScoredMemory],
        knowledge: List[ScoredKnowledge],
        longterm: List[ScoredMemory],
        identity: Optional[IdentitySummary],
    ) -> int:
        """Rough token estimation (~4 chars per token)."""
        total = 0
        for m in session:
            total += len(m.memory.summary or "") // 4
        for k in knowledge:
            total += len(k.knowledge.content or "") // 4
        for m in longterm:
            total += len(m.memory.summary or "") // 4
        if identity:
            total += 150  # Fixed identity overhead
        return total

    def _persist_pack(
        self,
        pack: CompiledPack,
        config: RetrievalConfig,
        preset_name: Optional[str] = None,
    ) -> None:
        """
        Persist a compiled pack to database.

        Also runs cleanup to enforce retention limit.
        """
        from app.domain.memory_pack_operations import MemoryPackOperations
        from app.models.database.memory_pack import MemoryPack as MemoryPackModel

        # Serialize pack content
        content = self._serialize_pack(pack)

        # Create database model
        db_pack = MemoryPackModel(
            anima_id=config.anima_id,
            query=config.query,
            preset_name=preset_name,
            session_memory_count=len(pack.session_memories),
            knowledge_count=len(pack.knowledge),
            long_term_memory_count=len(pack.long_term_memories),
            has_identity=pack.identity is not None,
            token_count=pack.token_count,
            max_tokens=config.max_tokens,
            content=content,
            compiled_at=pack.compiled_at,
        )

        # Persist
        MemoryPackOperations.create(self.session, db_pack)

        # Cleanup old packs (enforce retention)
        MemoryPackOperations.enforce_retention(
            self.session,
            config.anima_id,
            max_packs=self.DEFAULT_RETENTION_COUNT,
        )

    def _serialize_pack(self, pack: CompiledPack) -> Dict[str, Any]:
        """
        Serialize runtime CompiledPack to JSONB-compatible dict.

        Preserves full pack structure for later inspection.
        """
        content = {
            "context": pack.to_prompt_context(),
            "identity": None,
            "temporal_context": None,
            "session_memories": [],
            "knowledge": [],
            "long_term_memories": [],
            "config": {
                "anima_id": str(pack.config.anima_id),
                "query": pack.config.query,
                "session_window_hours": pack.config.session_window_hours,
                "max_session_memories": pack.config.max_session_memories,
                "max_knowledge": pack.config.max_knowledge,
                "max_long_term_memories": pack.config.max_long_term_memories,
                "max_tokens": pack.config.max_tokens,
                "similarity_threshold": pack.config.similarity_threshold,
                "include_identity": pack.config.include_identity,
                "include_temporal_awareness": pack.config.include_temporal_awareness,
                "weights": {
                    "importance": pack.config.weight_importance,
                    "confidence": pack.config.weight_confidence,
                    "recency": pack.config.weight_recency,
                    "decay": pack.config.weight_decay,
                    "similarity": pack.config.weight_similarity,
                },
            },
        }

        # Serialize identity
        if pack.identity:
            content["identity"] = {
                "name": pack.identity.name,
                "personality_type": pack.identity.personality_type,
                "communication_style": pack.identity.communication_style,
                "self_reflection": pack.identity.self_reflection,
            }

        # Serialize temporal context
        if pack.temporal_context:
            content["temporal_context"] = {
                "last_event_at": pack.temporal_context.last_event_at.isoformat(),
                "hours_ago": pack.temporal_context.hours_ago,
                "memory_summary": pack.temporal_context.memory_summary,
                "formatted": pack.temporal_context.formatted,
            }

        # Serialize session memories
        for sm in pack.session_memories:
            content["session_memories"].append({
                "id": str(sm.memory.id),
                "summary": sm.memory.summary,
                "score": sm.score,
                "reason": sm.retrieval_reason.value,
                "breakdown": sm.score_breakdown,
            })

        # Serialize knowledge
        for sk in pack.knowledge:
            content["knowledge"].append({
                "id": str(sk.knowledge.id),
                "content": sk.knowledge.content,
                "type": sk.knowledge.knowledge_type.value,
                "score": sk.score,
                "similarity": sk.similarity,
            })

        # Serialize long-term memories
        for ltm in pack.long_term_memories:
            content["long_term_memories"].append({
                "id": str(ltm.memory.id),
                "summary": ltm.memory.summary,
                "score": ltm.score,
                "reason": ltm.retrieval_reason.value,
                "breakdown": ltm.score_breakdown,
                "similarity": ltm.similarity,
            })

        return content
