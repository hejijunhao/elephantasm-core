"""
Memory Synthesis Workflow

Native async pipeline for automatic memory synthesis from accumulated events.

Main exports:
- run_memory_synthesis: Async function to execute synthesis pipeline
- MemorySynthesisResult: Typed result dataclass
- SYNTHESIS_THRESHOLD: Threshold constant for tuning
"""
from .pipeline import run_memory_synthesis
from .config import SYNTHESIS_THRESHOLD
from app.workflows.pipeline import MemorySynthesisResult

__all__ = [
    "run_memory_synthesis",
    "MemorySynthesisResult",
    "SYNTHESIS_THRESHOLD",
]
