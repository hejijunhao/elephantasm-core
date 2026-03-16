"""
Knowledge Synthesis Prompt Builder.

Constructs prompts for extracting structured Knowledge items from a Memory.
Separated from LLM client to enable prompt versioning and testing.
"""
from typing import Dict, Any


def build_knowledge_synthesis_prompt(memory: Dict[str, Any]) -> str:
    """
    Build knowledge synthesis prompt from Memory data.

    Extracts multiple Knowledge items with LLM-determined epistemic types and topics.
    Returns formatted prompt string ready for LLM.

    Args:
        memory: Serialized Memory dict with keys: summary, content, importance, confidence, etc.

    Returns:
        Formatted prompt string requesting JSON array of Knowledge items
    """
    memory_summary = memory.get('summary', '')
    memory_content = memory.get('content') or memory_summary
    importance = memory.get('importance', 'unknown')
    confidence = memory.get('confidence', 'unknown')

    return f"""Extract structured Knowledge items from this Memory:

MEMORY SUMMARY:
{memory_summary}

MEMORY CONTENT:
{memory_content}

MEMORY METADATA:
- Importance: {importance}
- Confidence: {confidence}

---

Your task is to extract discrete Knowledge items from this Memory. Each item should be atomic, well-defined, and categorized by epistemic type.

KNOWLEDGE TYPES (with examples):

1. FACT - Verifiable truth about the external world
   Example: "The user's name is Phil"
   Example: "Elephantasm uses FastAPI for the backend"
   Example: "The project started in mid-October 2025"

2. CONCEPT - Abstract framework, model, or mental construct
   Example: "Marlin Hybrid pattern: async API routes calling sync domain operations"
   Example: "Four-factor recall system: importance, confidence, recency, decay"
   Example: "Memory as a living system, not a cache"

3. METHOD - Procedural knowledge, how-to, causal understanding
   Example: "Use static methods in domain operations for stateless design"
   Example: "Disable prepared statements for pgBouncer compatibility"
   Example: "Soft delete via is_deleted flag preserves audit trail"

4. PRINCIPLE - Guiding belief, value, or normative statement
   Example: "Open-source models will dominate AI"
   Example: "Simplicity over complexity in architecture"
   Example: "Provenance is critical for memory systems"

5. EXPERIENCE - Personal, subjective, lived knowledge
   Example: "User prefers terminal/retro aesthetics"
   Example: "User found RLS implementation challenging"
   Example: "User values concise communication"

---

OUTPUT FORMAT:

Respond with a JSON array of Knowledge items. Each item must have:

{{
  "knowledge_type": "FACT" | "CONCEPT" | "METHOD" | "PRINCIPLE" | "EXPERIENCE",
  "content": "Complete, standalone statement (1-3 sentences)",
  "summary": "Brief one-line summary (for display)",
  "topic": "Semantic category/namespace (e.g., 'User Information', 'Project Architecture')"
}}

GUIDELINES:

1. **Be Atomic**: One knowledge item per fact/concept/method/etc. Don't combine unrelated items.
2. **Be Accurate**: Only extract what's explicitly stated or clearly implied. No hallucinations.
3. **Be Selective**: Not everything is worth extracting. Focus on meaningful, reusable knowledge.
4. **Be Specific**: Content should be standalone (readable without Memory context).
5. **Topics**: Create semantic namespaces that group related knowledge. Be consistent but not rigid.
6. **Empty is OK**: If the Memory contains no extractable knowledge (e.g., "Hello", "Thanks!"), return an empty array [].

CLASSIFICATION TIPS:

- FACT: Can be verified externally. Specific, concrete, time/space-bound.
- CONCEPT: Abstract mental models. Frameworks, patterns, definitions.
- METHOD: Actionable procedures. Steps, techniques, causal chains.
- PRINCIPLE: Normative judgments. Values, beliefs, preferences.
- EXPERIENCE: Subjective, personal. Feelings, preferences, observations.

When in doubt:
- "X is Y" → Usually FACT or CONCEPT (depending on abstraction level)
- "Do X to achieve Y" → METHOD
- "X should/must/ought to Y" → PRINCIPLE
- "I/User prefers/feels/experienced X" → EXPERIENCE

---

Return ONLY the JSON array, no additional text:

[
  {{
    "knowledge_type": "FACT",
    "content": "...",
    "summary": "...",
    "topic": "..."
  }},
  ...
]

If no knowledge is extractable, return: []
"""
