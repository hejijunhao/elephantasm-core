"""
Native workflow pipeline infrastructure.

Replaces LangGraph StateGraph with plain async function composition.
Each workflow is a single async function that calls steps sequentially,
passing a shared state dataclass. No checkpointing, no graph engine.

This module provides:
- PipelineResult: Base result container (success, error, timing)
- MemorySynthesisResult: Result from memory synthesis pipeline
- KnowledgeSynthesisResult: Result from knowledge synthesis pipeline

Usage (Phase 2+):
    from app.workflows.memory_synthesis.pipeline import run_memory_synthesis
    result = await run_memory_synthesis(anima_id)
    if result.success and not result.skipped:
        print(f"Created memory {result.memory_id}")
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PipelineResult:
    """Base result from any workflow pipeline."""

    success: bool = False
    error: str | None = None
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0

    def _finalize(self, start_time: float) -> None:
        """Set completion timestamp and duration. Called by pipeline runners."""
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.duration_ms = (time.perf_counter() - start_time) * 1000


@dataclass
class MemorySynthesisResult(PipelineResult):
    """
    Result from memory synthesis pipeline.

    Field contract matches what callers currently read from graph.ainvoke() state:
    - scheduler reads: synthesis_triggered, skip_reason, memory_id, error
    - hook reads: memory_id (to trigger knowledge synthesis)
    """

    # Scoring
    accumulation_score: float = 0.0
    time_factor: float = 0.0
    event_factor: float = 0.0
    token_factor: float = 0.0
    event_count: int = 0

    # Gate decision
    synthesis_triggered: bool = False
    skipped: bool = False
    skip_reason: str | None = None

    # Output
    memory_id: str | None = None
    provenance_links: list[str] = field(default_factory=list)
    embedding_generated: bool = False


@dataclass
class KnowledgeSynthesisResult(PipelineResult):
    """
    Result from knowledge synthesis pipeline.

    Field contract matches what callers currently read from graph.ainvoke() state:
    - hook reads: knowledge_ids, created_count, skip_reason, error
    - route reads: knowledge_ids, deleted_count, created_count, skip_reason, error
    """

    # Output
    knowledge_ids: list[str] = field(default_factory=list)
    deleted_count: int = 0
    created_count: int = 0

    # Control
    skip_reason: str | None = None
