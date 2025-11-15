"""
Memory Synthesis Prompt Builder.

Constructs prompts for transforming raw events into structured memories.
Separated from LLM client to enable prompt versioning and testing.
"""
from typing import List, Dict, Any


def build_memory_synthesis_prompt(events: List[Dict[str, Any]]) -> str:
    # Build synthesis prompt from raw event data (incl. content, summary, role, author, occurred_at). Returns formatted prompt string ready for LLM.
    events_text = "\n".join([
        _format_event(event, idx)
        for idx, event in enumerate(events, 1)
    ])

    return f"""Synthesize a memory from these events:

    {events_text}

Analyze the events and create a cohesive memory summary. Respond with JSON:

{{
  "summary": "1-2 sentence memory summary capturing the essence",
  "content": "Optional detailed narrative (2-3 sentences) or null",
  "importance": 0.0-1.0 (how significant is this memory?),
  "confidence": 0.0-1.0 (how certain/stable is this memory?)
}}

Guidelines:
- Focus on what matters (filter noise)
- Capture key insights, not just facts
- Importance: novelty, emotional weight, decision points
- Confidence: clarity, consistency, corroboration across events"""


def _format_event(event: Dict, index: int) -> str:
    # Format single event for inclusion in prompt (args: event, index - returns formatted event string for prompt)
    role = event.get('role', 'unknown')
    author = event.get('author', 'unknown')
    timestamp = event.get('occurred_at', 'unknown')

    # Use summary if available, otherwise truncate content
    text = event.get('summary') or event.get('content', '')[:200]

    return f"[{index}] {timestamp} | {role} ({author}): {text}"
