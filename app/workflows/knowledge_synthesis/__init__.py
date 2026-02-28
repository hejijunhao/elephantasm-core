"""
Knowledge Synthesis Workflow.

Exports graph builder and singleton accessor for workflow execution.
"""
from .graph import get_knowledge_synthesis_graph, build_knowledge_synthesis_graph

__all__ = [
    "get_knowledge_synthesis_graph",
    "build_knowledge_synthesis_graph",
]
