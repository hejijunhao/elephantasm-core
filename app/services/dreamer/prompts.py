"""
Deep Sleep Prompt Templates

LLM prompt builders for memory curation decisions:
- Merge: Combine redundant memories into coherent wholes
- Review: Assess and refine individual memories
- Delete: Identify noise for removal

Separated from LLM infrastructure to enable prompt versioning and testing.
"""

from typing import Any

from app.models.database.identity import Identity
from app.models.database.knowledge import Knowledge
from app.models.database.memories import Memory


def build_merge_prompt(
    memories: list[Memory],
    identity: Identity | None = None,
    knowledge: list[Knowledge] | None = None,
) -> str:
    """
    Build prompt for evaluating and merging redundant memories.

    Args:
        memories: List of potentially redundant memories to evaluate
        identity: Anima's identity (curation lens)
        knowledge: Existing knowledge (to avoid redundancy)

    Returns:
        Formatted prompt requesting merge decision
    """
    # Format memories for context
    memories_text = _format_memories_for_prompt(memories)

    # Format identity context
    identity_text = _format_identity_for_prompt(identity)

    # Format knowledge context (brief summary)
    knowledge_text = _format_knowledge_for_prompt(knowledge)

    return f"""You are a memory curator for an AI agent. Your task is to evaluate whether the following memories should be merged into a single, coherent memory.

IDENTITY CONTEXT (the agent's personality and values):
{identity_text}

EXISTING KNOWLEDGE (avoid redundancy with these):
{knowledge_text}

---

MEMORIES TO EVALUATE:

{memories_text}

---

EVALUATION CRITERIA:

1. **Semantic Overlap**: Do these memories describe the same concept, event, or insight?
2. **Complementary Information**: Do they add different perspectives on the same thing?
3. **Temporal Coherence**: Do they refer to the same time period or ongoing pattern?
4. **Identity Relevance**: Are they equally important to the agent's identity/purpose?

MERGE DECISION:

- **MERGE** if memories are redundant, overlapping, or describe the same thing differently
- **KEEP_SEPARATE** if memories are distinct concepts that happen to be similar

---

OUTPUT FORMAT:

Respond with a JSON object:

{{
  "should_merge": true | false,
  "reasoning": "Brief explanation of your decision (1-2 sentences)",
  "merged_summary": "If merging, the unified summary that captures all information (null if not merging)",
  "importance": 0.0-1.0 (combined importance score, null if not merging),
  "confidence": 0.0-1.0 (confidence in the merged memory, null if not merging)
}}

GUIDELINES for merged_summary:
- Preserve all unique information from source memories
- Be concise but complete (aim for 1-3 sentences)
- Use the agent's voice/perspective
- Don't add information not present in the sources

Return ONLY the JSON object, no additional text.
"""


def build_review_prompt(
    memories: list[Memory],
    identity: Identity | None = None,
    knowledge: list[Knowledge] | None = None,
) -> str:
    """
    Build prompt for reviewing and refining a batch of memories.

    Args:
        memories: Memories to review (flagged for low confidence, short summary, etc.)
        identity: Anima's identity (curation lens)
        knowledge: Existing knowledge context

    Returns:
        Formatted prompt requesting curation decisions for each memory
    """
    memories_text = _format_memories_for_prompt(memories, include_index=True)
    identity_text = _format_identity_for_prompt(identity)
    knowledge_text = _format_knowledge_for_prompt(knowledge)

    return f"""You are a memory curator for an AI agent. Review the following memories and decide what action to take for each.

IDENTITY CONTEXT (the agent's personality and values):
{identity_text}

EXISTING KNOWLEDGE (for context):
{knowledge_text}

---

MEMORIES TO REVIEW:

{memories_text}

---

For each memory, choose ONE action:

1. **KEEP**: Memory is well-formed and valuable. No changes needed.

2. **UPDATE**: Memory needs refinement (clearer summary, adjusted scores, expanded content).
   - Provide: new_summary, new_importance (0.0-1.0), new_confidence (0.0-1.0)

3. **SPLIT**: Memory conflates multiple distinct concepts that should be separate.
   - Provide: split_into (array of 2-4 distinct summaries)

4. **DELETE**: Memory is noise, redundant with knowledge, or not useful.
   - Provide: reasoning for deletion

---

OUTPUT FORMAT:

Respond with a JSON array, one decision per memory (match by index):

[
  {{
    "index": 0,
    "action": "KEEP" | "UPDATE" | "SPLIT" | "DELETE",
    "reasoning": "Brief explanation (1 sentence)",
    "new_summary": "Updated summary if UPDATE (null otherwise)",
    "new_importance": 0.0-1.0 if UPDATE (null otherwise),
    "new_confidence": 0.0-1.0 if UPDATE (null otherwise),
    "split_into": ["summary1", "summary2"] if SPLIT (null otherwise)
  }},
  ...
]

GUIDELINES:

- **Be conservative**: When in doubt, KEEP. Don't delete valuable memories.
- **Identity lens**: Prioritize memories that align with the agent's purpose/values.
- **Quality over quantity**: A well-curated few memories > many mediocre ones.
- **SPLIT sparingly**: Only if a memory truly contains distinct, unrelated concepts.
- **DELETE rarely**: Only for true noise (greetings, acknowledgments, duplicates).

Return ONLY the JSON array, no additional text.
"""


def _format_memories_for_prompt(
    memories: list[Memory],
    include_index: bool = False,
) -> str:
    """Format memories for inclusion in prompts."""
    if not memories:
        return "(no memories)"

    parts: list[str] = []

    for i, memory in enumerate(memories):
        prefix = f"[{i}] " if include_index else "- "

        summary = memory.summary or "(no summary)"
        importance = memory.importance or 0.5
        confidence = memory.confidence or 0.5
        state = memory.state.value if memory.state else "UNKNOWN"

        # Include content preview if available
        content_preview = ""
        if memory.content:
            preview = memory.content[:200]
            if len(memory.content) > 200:
                preview += "..."
            content_preview = f"\n  Content: {preview}"

        parts.append(
            f"{prefix}ID: {memory.id}\n"
            f"  Summary: {summary}\n"
            f"  Importance: {importance:.2f} | Confidence: {confidence:.2f} | State: {state}"
            f"{content_preview}"
        )

    return "\n\n".join(parts)


def _format_identity_for_prompt(identity: Identity | None) -> str:
    """Format identity for inclusion in prompts."""
    if not identity:
        return "(no identity defined - use general best judgment)"

    parts: list[str] = []

    if identity.personality_type:
        parts.append(f"Personality: {identity.personality_type.value}")

    if identity.communication_style:
        parts.append(f"Communication style: {identity.communication_style}")

    # Include principles if available in self JSONB
    if identity.self_:
        principles = identity.self_.get("principles", [])
        if principles:
            parts.append(f"Principles: {', '.join(principles[:5])}")

        epistemology = identity.self_.get("epistemology")
        if epistemology:
            parts.append(f"Epistemology: {epistemology}")

    return "\n".join(parts) if parts else "(minimal identity)"


def _format_knowledge_for_prompt(
    knowledge: list[Knowledge] | None,
    max_items: int = 10,
) -> str:
    """Format knowledge for inclusion in prompts (brief summary)."""
    if not knowledge:
        return "(no existing knowledge)"

    # Take most recent/relevant items
    items = knowledge[:max_items]

    parts: list[str] = []
    for k in items:
        k_type = k.knowledge_type.value if k.knowledge_type else "UNKNOWN"
        summary = k.summary or k.content[:100] if k.content else "(no content)"
        parts.append(f"- [{k_type}] {summary}")

    suffix = ""
    if len(knowledge) > max_items:
        suffix = f"\n... and {len(knowledge) - max_items} more"

    return "\n".join(parts) + suffix


# ─────────────────────────────────────────────────────────────────
# Response Parsing
# ─────────────────────────────────────────────────────────────────


def parse_merge_response(response: dict[str, Any]) -> "MergeDecision":
    """
    Parse and validate merge decision from LLM response.

    Args:
        response: Parsed JSON dict from LLM

    Returns:
        MergeDecision dataclass

    Raises:
        ValueError: If response is malformed
    """
    should_merge = response.get("should_merge", False)
    reasoning = response.get("reasoning", "No reasoning provided")

    if should_merge:
        merged_summary = response.get("merged_summary")
        if not merged_summary:
            raise ValueError("Merge decision missing merged_summary")

        importance = response.get("importance", 0.5)
        confidence = response.get("confidence", 0.5)

        # Clamp to valid range
        importance = max(0.0, min(1.0, float(importance)))
        confidence = max(0.0, min(1.0, float(confidence)))

        return MergeDecision(
            should_merge=True,
            reasoning=reasoning,
            merged_summary=merged_summary,
            importance=importance,
            confidence=confidence,
        )

    return MergeDecision(
        should_merge=False,
        reasoning=reasoning,
        merged_summary=None,
        importance=None,
        confidence=None,
    )


def parse_review_response(response: list[dict[str, Any]]) -> list["ReviewDecision"]:
    """
    Parse and validate review decisions from LLM response.

    Args:
        response: Parsed JSON array from LLM

    Returns:
        List of ReviewDecision dataclasses

    Raises:
        ValueError: If response is malformed
    """
    if not isinstance(response, list):
        raise ValueError("Review response must be a JSON array")

    decisions: list[ReviewDecision] = []

    for item in response:
        index = item.get("index", len(decisions))
        action = item.get("action", "KEEP").upper()
        reasoning = item.get("reasoning", "No reasoning provided")

        if action == "KEEP":
            decisions.append(
                ReviewDecision(
                    index=index,
                    action="KEEP",
                    reasoning=reasoning,
                )
            )

        elif action == "UPDATE":
            new_summary = item.get("new_summary")
            new_importance = item.get("new_importance")
            new_confidence = item.get("new_confidence")

            # Validate at least one update field
            if not any([new_summary, new_importance is not None, new_confidence is not None]):
                # Treat as KEEP if no actual updates
                decisions.append(
                    ReviewDecision(index=index, action="KEEP", reasoning=reasoning)
                )
                continue

            # Clamp scores to valid range
            if new_importance is not None:
                new_importance = max(0.0, min(1.0, float(new_importance)))
            if new_confidence is not None:
                new_confidence = max(0.0, min(1.0, float(new_confidence)))

            decisions.append(
                ReviewDecision(
                    index=index,
                    action="UPDATE",
                    reasoning=reasoning,
                    new_summary=new_summary,
                    new_importance=new_importance,
                    new_confidence=new_confidence,
                )
            )

        elif action == "SPLIT":
            split_into = item.get("split_into", [])
            if not isinstance(split_into, list) or len(split_into) < 2:
                # Invalid split, treat as KEEP
                decisions.append(
                    ReviewDecision(
                        index=index,
                        action="KEEP",
                        reasoning=f"Invalid split (need 2+ summaries): {reasoning}",
                    )
                )
                continue

            decisions.append(
                ReviewDecision(
                    index=index,
                    action="SPLIT",
                    reasoning=reasoning,
                    split_into=split_into,
                )
            )

        elif action == "DELETE":
            decisions.append(
                ReviewDecision(
                    index=index,
                    action="DELETE",
                    reasoning=reasoning,
                )
            )

        else:
            # Unknown action, default to KEEP
            decisions.append(
                ReviewDecision(
                    index=index,
                    action="KEEP",
                    reasoning=f"Unknown action '{action}', keeping",
                )
            )

    return decisions


# ─────────────────────────────────────────────────────────────────
# Decision Dataclasses
# ─────────────────────────────────────────────────────────────────


from dataclasses import dataclass, field


@dataclass
class MergeDecision:
    """Result of merge evaluation."""

    should_merge: bool
    reasoning: str
    merged_summary: str | None = None
    importance: float | None = None
    confidence: float | None = None


@dataclass
class ReviewDecision:
    """Result of individual memory review."""

    index: int
    action: str  # KEEP, UPDATE, SPLIT, DELETE
    reasoning: str
    new_summary: str | None = None
    new_importance: float | None = None
    new_confidence: float | None = None
    split_into: list[str] = field(default_factory=list)
