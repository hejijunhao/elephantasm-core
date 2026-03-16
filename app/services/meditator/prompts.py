"""
Contemplation Prompt Templates

LLM prompt builders for knowledge curation decisions:
- Merge: Combine redundant knowledge pairs into coherent wholes
- Consolidate: Reduce clusters of related knowledge into the minimum essential set
- Review: Assess and refine individual knowledge (KEEP/UPDATE/RECLASSIFY/SPLIT/DELETE)

Adapted from Dreamer's prompts for the Knowledge domain.
Key differences:
- Include knowledge_type and topic in each item's representation
- RECLASSIFY as a valid review action (type/topic change without content change)
- Context includes recent Memories (what the Anima has been learning)
- Prompts emphasize epistemic coherence
"""

from dataclasses import dataclass, field
from typing import Any

from app.models.database.identity import Identity
from app.models.database.knowledge import Knowledge
from app.models.database.memories import Memory


# ─────────────────────────────────────────────────────────────────
# Prompt Builders
# ─────────────────────────────────────────────────────────────────


def build_knowledge_merge_prompt(
    knowledge_items: list[Knowledge],
    identity: Identity | None = None,
    memories: list[Memory] | None = None,
) -> str:
    """Build prompt for evaluating and merging redundant knowledge items."""
    items_text = _format_knowledge_for_prompt(knowledge_items)
    identity_text = _format_identity_for_prompt(identity)
    memories_text = _format_memories_for_prompt(memories)

    return f"""You are a knowledge curator for an AI agent. Your task is to evaluate whether the following knowledge items should be merged into a single, coherent knowledge item.

IDENTITY CONTEXT (the agent's personality and values):
{identity_text}

RECENT LEARNING (what the agent has been learning):
{memories_text}

---

KNOWLEDGE ITEMS TO EVALUATE:

{items_text}

---

EVALUATION CRITERIA:

1. **Semantic Overlap**: Do these items describe the same concept, fact, or principle?
2. **Complementary Information**: Do they add different facets of the same knowledge?
3. **Epistemic Coherence**: Would merging improve the agent's knowledge base consistency?
4. **Type Compatibility**: Are they the same knowledge_type? Merging across types should be rare.

MERGE DECISION:

- **MERGE** if items are redundant, overlapping, or describe the same thing differently
- **KEEP_SEPARATE** if items are genuinely distinct knowledge that happen to share a topic

---

OUTPUT FORMAT:

Respond with a JSON object:

{{
  "should_merge": true | false,
  "reasoning": "Brief explanation of your decision (1-2 sentences)",
  "merged_content": "If merging, the unified content that captures all information (null if not merging)",
  "merged_summary": "If merging, a concise one-liner (null if not merging)",
  "knowledge_type": "FACT|CONCEPT|METHOD|PRINCIPLE|EXPERIENCE (type for merged item, null if not merging)",
  "topic": "Topic for merged item (null if not merging)",
  "confidence": 0.85 (float 0.0-1.0, confidence in the merged knowledge, null if not merging)
}}

GUIDELINES for merged_content:
- Preserve all unique information from source items
- Be precise and factual
- Don't add information not present in the sources
- Use the agent's perspective

Return ONLY the JSON object, no additional text.
"""


def build_knowledge_consolidation_prompt(
    knowledge_items: list[Knowledge],
    identity: Identity | None = None,
    memories: list[Memory] | None = None,
    summaries_only: bool = False,
) -> str:
    """Build prompt for consolidating a cluster of related knowledge items."""
    items_text = _format_knowledge_for_consolidation(
        knowledge_items, summaries_only=summaries_only
    )
    identity_text = _format_identity_for_prompt(identity)
    memories_text = _format_memories_for_prompt(memories)

    content_note = ""
    if summaries_only:
        content_note = (
            "\nNOTE: Only summaries are shown (content omitted for brevity). "
            "Base your consolidation on the summary text."
        )

    return f"""You are a knowledge curator for an AI agent. You have been given a cluster of {len(knowledge_items)} related knowledge items. Your task is to consolidate them into the MINIMUM set of distinct knowledge items that preserves all meaningful information.

IDENTITY CONTEXT (the agent's personality and values):
{identity_text}

RECENT LEARNING (what the agent has been learning):
{memories_text}

---

KNOWLEDGE ITEMS TO CONSOLIDATE:{content_note}

{items_text}

---

INSTRUCTIONS:

- Identify the distinct concepts/facts/principles across these items
- Merge items that describe the same thing into ONE consolidated item
- Keep items separate if they represent genuinely different knowledge
- Aim for the MINIMUM number of output items (often 2-4 for large clusters)
- Each output should be a self-contained, coherent knowledge statement
- Preserve all meaningful unique information — don't lose important details
- Maintain appropriate knowledge_type for each output
- Preserve epistemic coherence — the knowledge base should tell a consistent story

OUTPUT FORMAT:

Respond with a JSON object:

{{
  "reasoning": "Brief explanation of how you grouped and consolidated (1-3 sentences)",
  "consolidated_knowledge": [
    {{
      "content": "Full knowledge statement",
      "summary": "Concise one-liner",
      "knowledge_type": "FACT|CONCEPT|METHOD|PRINCIPLE|EXPERIENCE",
      "topic": "Topic grouping",
      "confidence": 0.85,
      "source_indices": [0, 3, 7]
    }}
  ]
}}

GUIDELINES:

- source_indices maps to the [index] of input items each output consolidates
- Every input item should appear in at least one output's source_indices
- confidence: high (0.7-0.9) for well-supported consolidations, lower if sources conflict
- knowledge_type: use the most appropriate type for the consolidated content

Return ONLY the JSON object, no additional text.
"""


def build_knowledge_review_prompt(
    knowledge_items: list[Knowledge],
    identity: Identity | None = None,
    memories: list[Memory] | None = None,
) -> str:
    """Build prompt for reviewing and refining a batch of knowledge items."""
    items_text = _format_knowledge_for_prompt(knowledge_items, include_index=True)
    identity_text = _format_identity_for_prompt(identity)
    memories_text = _format_memories_for_prompt(memories)

    return f"""You are a knowledge curator for an AI agent. Review the following knowledge items and decide what action to take for each.

IDENTITY CONTEXT (the agent's personality and values):
{identity_text}

RECENT LEARNING (what the agent has been learning):
{memories_text}

---

KNOWLEDGE ITEMS TO REVIEW:

{items_text}

---

For each item, choose ONE action:

1. **KEEP**: Item is well-formed, accurate, and valuable. No changes needed.

2. **UPDATE**: Item needs refinement (clearer content, adjusted confidence, expanded detail).
   - Provide: new_content, new_summary, new_confidence (0.0-1.0)

3. **RECLASSIFY**: Item's knowledge_type or topic is wrong. Content stays the same.
   - Provide: new_knowledge_type (FACT|CONCEPT|METHOD|PRINCIPLE|EXPERIENCE) and/or new_topic

4. **SPLIT**: Item conflates multiple distinct concepts that should be separate.
   - Provide: split_into (array of 2-4 distinct definitions, each with content + knowledge_type + topic)

5. **DELETE**: Item is noise, outdated, contradicted by newer knowledge, or not useful.
   - Provide: reasoning for deletion

---

OUTPUT FORMAT:

Respond with a JSON array, one decision per item (match by index):

[
  {{
    "index": 0,
    "action": "KEEP" | "UPDATE" | "RECLASSIFY" | "SPLIT" | "DELETE",
    "reasoning": "Brief explanation (1 sentence)",
    "new_content": "Updated content if UPDATE (null otherwise)",
    "new_summary": "Updated summary if UPDATE (null otherwise)",
    "new_confidence": 0.85 if UPDATE (null otherwise),
    "new_knowledge_type": "FACT|CONCEPT|METHOD|PRINCIPLE|EXPERIENCE if RECLASSIFY (null otherwise)",
    "new_topic": "New topic if RECLASSIFY (null otherwise)",
    "split_into": [
      {{"content": "...", "knowledge_type": "...", "topic": "..."}}
    ] if SPLIT (null otherwise)
  }},
  ...
]

GUIDELINES:

- **Be conservative**: When in doubt, KEEP. Don't delete valuable knowledge.
- **Epistemic coherence**: Does the knowledge base tell a consistent, non-contradictory story?
- **RECLASSIFY** when the content is fine but the categorization is wrong
- **SPLIT** only if an item truly contains distinct, unrelated concepts
- **DELETE** rarely: only for true noise, contradictions, or superseded knowledge

Return ONLY the JSON array, no additional text.
"""


# ─────────────────────────────────────────────────────────────────
# Formatting Helpers
# ─────────────────────────────────────────────────────────────────


def _format_knowledge_for_prompt(
    knowledge: list[Knowledge],
    include_index: bool = False,
) -> str:
    """Format knowledge items for inclusion in prompts."""
    if not knowledge:
        return "(no knowledge items)"

    parts: list[str] = []

    for i, k in enumerate(knowledge):
        prefix = f"[{i}] " if include_index else "- "
        k_type = k.knowledge_type.value if k.knowledge_type else "UNKNOWN"
        topic = k.topic or "(no topic)"
        confidence = k.confidence if k.confidence is not None else 0.5

        content_preview = ""
        if k.content:
            preview = k.content[:300]
            if len(k.content) > 300:
                preview += "..."
            content_preview = f"\n  Content: {preview}"

        summary_text = ""
        if k.summary:
            summary_text = f"\n  Summary: {k.summary}"

        parts.append(
            f"{prefix}ID: {k.id}\n"
            f"  Type: {k_type} | Topic: {topic} | Confidence: {confidence:.2f}"
            f"{summary_text}"
            f"{content_preview}"
        )

    return "\n\n".join(parts)


def _format_knowledge_for_consolidation(
    knowledge: list[Knowledge],
    summaries_only: bool = False,
) -> str:
    """Format knowledge for consolidation prompt with indexed references."""
    if not knowledge:
        return "(no knowledge items)"

    parts: list[str] = []

    for i, k in enumerate(knowledge):
        k_type = k.knowledge_type.value if k.knowledge_type else "UNKNOWN"
        topic = k.topic or "(no topic)"
        confidence = k.confidence if k.confidence is not None else 0.5
        summary = k.summary or "(no summary)"

        entry = (
            f"[{i}] Type: {k_type} | Topic: {topic} | Confidence: {confidence:.2f}\n"
            f"     Summary: {summary}"
        )

        if not summaries_only and k.content:
            content = k.content[:500]
            if len(k.content) > 500:
                content += "..."
            entry += f"\n     Content: {content}"

        parts.append(entry)

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

    if identity.self_ and isinstance(identity.self_, dict):
        principles = identity.self_.get("principles", [])
        if isinstance(principles, list) and principles:
            str_principles = [str(p) for p in principles[:5]]
            parts.append(f"Principles: {', '.join(str_principles)}")

        epistemology = identity.self_.get("epistemology")
        if epistemology:
            parts.append(f"Epistemology: {epistemology}")

    return "\n".join(parts) if parts else "(minimal identity)"


def _format_memories_for_prompt(
    memories: list[Memory] | None,
    max_items: int = 10,
) -> str:
    """Format recent memories for inclusion in prompts (context for what Anima is learning)."""
    if not memories:
        return "(no recent learning context)"

    items = memories[:max_items]

    parts: list[str] = []
    for m in items:
        summary = m.summary or "(no summary)"
        parts.append(f"- {summary}")

    suffix = ""
    if len(memories) > max_items:
        suffix = f"\n... and {len(memories) - max_items} more recent memories"

    return "\n".join(parts) + suffix


# ─────────────────────────────────────────────────────────────────
# Response Parsing
# ─────────────────────────────────────────────────────────────────


def parse_knowledge_merge_response(response: dict[str, Any]) -> "KnowledgeMergeDecision":
    """Parse and validate merge decision from LLM response."""
    should_merge = response.get("should_merge", False)
    reasoning = response.get("reasoning", "No reasoning provided")

    if should_merge:
        merged_content = response.get("merged_content")
        if not merged_content:
            raise ValueError("Merge decision missing merged_content")

        confidence = float(response.get("confidence") or 0.5)
        confidence = max(0.0, min(1.0, confidence))

        return KnowledgeMergeDecision(
            should_merge=True,
            reasoning=reasoning,
            merged_content=merged_content,
            merged_summary=response.get("merged_summary"),
            knowledge_type=response.get("knowledge_type"),
            topic=response.get("topic"),
            confidence=confidence,
        )

    return KnowledgeMergeDecision(
        should_merge=False,
        reasoning=reasoning,
    )


def parse_knowledge_consolidation_response(
    response: dict[str, Any],
    num_source_items: int,
) -> "KnowledgeConsolidationDecision":
    """Parse and validate consolidation decision from LLM response."""
    reasoning = response.get("reasoning", "No reasoning provided")
    raw_items = response.get("consolidated_knowledge", [])

    if not isinstance(raw_items, list) or len(raw_items) == 0:
        raise ValueError("Consolidation response missing consolidated_knowledge array")

    consolidated: list[ConsolidatedKnowledge] = []

    for item in raw_items:
        content = item.get("content")
        if not content:
            continue

        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.5)))

        raw_indices = item.get("source_indices", [])
        if not isinstance(raw_indices, list):
            raw_indices = []
        valid_indices = [
            int(idx) for idx in raw_indices
            if isinstance(idx, (int, float)) and 0 <= int(idx) < num_source_items
        ]
        if not valid_indices:
            valid_indices = list(range(num_source_items))

        consolidated.append(ConsolidatedKnowledge(
            content=content,
            summary=item.get("summary"),
            knowledge_type=item.get("knowledge_type"),
            topic=item.get("topic"),
            confidence=confidence,
            source_indices=valid_indices,
        ))

    if not consolidated:
        raise ValueError("No valid consolidated knowledge in response")

    return KnowledgeConsolidationDecision(
        reasoning=reasoning,
        consolidated_knowledge=consolidated,
    )


def parse_knowledge_review_response(
    response: list[dict[str, Any]],
) -> list["KnowledgeReviewDecision"]:
    """Parse and validate review decisions from LLM response."""
    if not isinstance(response, list):
        raise ValueError("Review response must be a JSON array")

    decisions: list[KnowledgeReviewDecision] = []

    for item in response:
        raw_index = item.get("index")
        if raw_index is None:
            continue  # Skip decisions without explicit index — fallback could target wrong item
        index = int(raw_index)
        action = item.get("action", "KEEP").upper()
        reasoning = item.get("reasoning", "No reasoning provided")

        if action == "KEEP":
            decisions.append(KnowledgeReviewDecision(
                index=index, action="KEEP", reasoning=reasoning,
            ))

        elif action == "UPDATE":
            new_content = item.get("new_content")
            new_summary = item.get("new_summary")
            new_confidence = item.get("new_confidence")

            if not any([new_content, new_summary, new_confidence is not None]):
                decisions.append(KnowledgeReviewDecision(
                    index=index, action="KEEP", reasoning=reasoning,
                ))
                continue

            if new_confidence is not None:
                new_confidence = max(0.0, min(1.0, float(new_confidence)))

            decisions.append(KnowledgeReviewDecision(
                index=index, action="UPDATE", reasoning=reasoning,
                new_content=new_content, new_summary=new_summary,
                new_confidence=new_confidence,
            ))

        elif action == "RECLASSIFY":
            new_type = item.get("new_knowledge_type")
            new_topic = item.get("new_topic")

            if not new_type and not new_topic:
                decisions.append(KnowledgeReviewDecision(
                    index=index, action="KEEP",
                    reasoning=f"Invalid reclassify (no type/topic): {reasoning}",
                ))
                continue

            decisions.append(KnowledgeReviewDecision(
                index=index, action="RECLASSIFY", reasoning=reasoning,
                new_knowledge_type=new_type, new_topic=new_topic,
            ))

        elif action == "SPLIT":
            split_into = item.get("split_into", [])
            if not isinstance(split_into, list) or len(split_into) < 2:
                decisions.append(KnowledgeReviewDecision(
                    index=index, action="KEEP",
                    reasoning=f"Invalid split (need 2+ items): {reasoning}",
                ))
                continue

            decisions.append(KnowledgeReviewDecision(
                index=index, action="SPLIT", reasoning=reasoning,
                split_into=split_into,
            ))

        elif action == "DELETE":
            decisions.append(KnowledgeReviewDecision(
                index=index, action="DELETE", reasoning=reasoning,
            ))

        else:
            decisions.append(KnowledgeReviewDecision(
                index=index, action="KEEP",
                reasoning=f"Unknown action '{action}', keeping",
            ))

    return decisions


# ─────────────────────────────────────────────────────────────────
# Decision Dataclasses
# ─────────────────────────────────────────────────────────────────


@dataclass
class KnowledgeMergeDecision:
    """Result of knowledge merge evaluation."""
    should_merge: bool
    reasoning: str
    merged_content: str | None = None
    merged_summary: str | None = None
    knowledge_type: str | None = None
    topic: str | None = None
    confidence: float | None = None


@dataclass
class KnowledgeReviewDecision:
    """Result of individual knowledge review."""
    index: int
    action: str  # KEEP, UPDATE, RECLASSIFY, SPLIT, DELETE
    reasoning: str
    new_content: str | None = None
    new_summary: str | None = None
    new_confidence: float | None = None
    new_knowledge_type: str | None = None
    new_topic: str | None = None
    split_into: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ConsolidatedKnowledge:
    """Single output item from cluster consolidation."""
    content: str
    summary: str | None
    knowledge_type: str | None
    topic: str | None
    confidence: float
    source_indices: list[int]


@dataclass
class KnowledgeConsolidationDecision:
    """Result of cluster consolidation."""
    reasoning: str
    consolidated_knowledge: list[ConsolidatedKnowledge]
