"""
Memory Synthesis Workflow

LangGraph-based automatic memory synthesis from accumulated events.

Main exports:
- get_memory_synthesis_graph: Async function to get/build compiled StateGraph
- build_memory_synthesis_graph: Async function to build new graph instance
- MemorySynthesisState: TypedDict state schema
- SYNTHESIS_THRESHOLD: Threshold constant for tuning
"""
from .graph import get_memory_synthesis_graph, build_memory_synthesis_graph
from .state import MemorySynthesisState
from .config import SYNTHESIS_THRESHOLD

__all__ = [
    "get_memory_synthesis_graph",
    "build_memory_synthesis_graph",
    "MemorySynthesisState",
    "SYNTHESIS_THRESHOLD",
]
