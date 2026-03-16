"""
Knowledge Synthesis Workflow

Native async pipeline for extracting Knowledge items from Memories via LLM.

Main exports:
- run_knowledge_synthesis: Async function to execute synthesis pipeline
- KnowledgeSynthesisResult: Typed result dataclass
"""
from .pipeline import run_knowledge_synthesis
from app.workflows.pipeline import KnowledgeSynthesisResult

__all__ = [
    "run_knowledge_synthesis",
    "KnowledgeSynthesisResult",
]
