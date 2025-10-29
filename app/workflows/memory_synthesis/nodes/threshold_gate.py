"""
Threshold Gate Node

Evaluates whether accumulation score meets synthesis threshold.
Acts as decision gate: score >= threshold → proceed to synthesis.
"""
from ..state import MemorySynthesisState
from ..config import SYNTHESIS_THRESHOLD


def check_synthesis_threshold_node(state: MemorySynthesisState) -> dict:
    """
    Check if accumulation score meets synthesis threshold.
    Graph conditional edge will route based on synthesis_triggered field.
    Routing Logic (handled by graph conditional edge):
        synthesis_triggered=True  → "collect_pending_events" (proceed to synthesis)
        synthesis_triggered=False → "skip_synthesis" (exit workflow early)
    """
    score = state.get("accumulation_score", 0.0)
    triggered = score >= SYNTHESIS_THRESHOLD

    return {"synthesis_triggered": triggered}


def route_after_threshold_check(state: MemorySynthesisState) -> str:
    """
    Conditional routing function for graph edges.

    Used by StateGraph.add_conditional_edges() to determine next node.
    """
    if state.get("synthesis_triggered", False):
        return "collect_pending_events"
    else:
        return "skip_synthesis"
