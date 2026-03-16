"""
Knowledge Synthesis (LLM)

Calls LLM to extract Knowledge items from Memory.
Core intelligence node — transforms Memory into structured Knowledge (multi-output).

Validates LLM response structure and enforces quality controls.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

from ..config import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    MAX_KNOWLEDGE_ITEMS_PER_MEMORY,
    MIN_CONTENT_LENGTH,
    MAX_CONTENT_LENGTH,
    MIN_SUMMARY_LENGTH,
    MAX_SUMMARY_LENGTH,
    DEFAULT_TOPIC,
    ERROR_LLM_RESPONSE_INVALID,
    ERROR_REQUIRED_FIELD_MISSING,
    ERROR_INVALID_KNOWLEDGE_TYPE,
    SKIP_REASON_NO_EXTRACTIONS,
    VALIDATE_ENUM_STRICT,
)
from ..prompts import build_knowledge_synthesis_prompt
from app.services.llm import get_llm_client
from app.models.database.knowledge import KnowledgeType


@dataclass
class KnowledgeSynthesisLLMResult:
    """Result from knowledge synthesis LLM step."""

    llm_response: List[Dict[str, Any]] = field(default_factory=list)
    skip_reason: Optional[str] = None
    error: Optional[str] = None


async def synthesize_knowledge(
    memory_data: Dict[str, Any],
) -> KnowledgeSynthesisLLMResult:
    """
    Synthesize Knowledge items from Memory via LLM.

    Calls LLM with Memory content, parses JSON array response,
    validates structure and enforces quality controls.
    Errors are captured in the result, not raised.

    Args:
        memory_data: Serialized Memory dict from fetch step

    Returns:
        KnowledgeSynthesisLLMResult with validated knowledge items or skip_reason/error
    """
    if not memory_data:
        return KnowledgeSynthesisLLMResult(
            error="No memory_data provided (fetch step failed?)",
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Build prompt from Memory data
    try:
        prompt = build_knowledge_synthesis_prompt(memory_data)
    except Exception as e:
        return KnowledgeSynthesisLLMResult(
            error=f"Failed to build prompt: {str(e)}",
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Get LLM client (provider selected via config)
    llm_client = get_llm_client()

    # Call LLM with default parameters (automatic retry logic in client)
    memory_id = memory_data.get('id', 'unknown')
    logger.info(f"Calling LLM for Memory {memory_id} knowledge synthesis")

    try:
        response_text = await llm_client.call(
            prompt,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS
        )
        logger.info(f"LLM response received for Memory {memory_id} ({len(response_text)} chars)")
    except Exception as e:
        error_msg = f"LLM API call failed: {str(e)}"
        logger.error(f"{error_msg} | Memory: {memory_id} | Exception: {type(e).__name__}")
        return KnowledgeSynthesisLLMResult(
            error=error_msg,
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Parse JSON response (expects array)
    try:
        llm_response = llm_client.parse_json_response(response_text)
    except Exception as e:
        return KnowledgeSynthesisLLMResult(
            error=f"{ERROR_LLM_RESPONSE_INVALID}: {str(e)}",
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Validate response is array
    if not isinstance(llm_response, list):
        return KnowledgeSynthesisLLMResult(
            error=f"{ERROR_LLM_RESPONSE_INVALID}: Expected array, got {type(llm_response).__name__}",
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Empty array is valid (minimal Memory with no extractable knowledge)
    if len(llm_response) == 0:
        return KnowledgeSynthesisLLMResult(
            llm_response=[],
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
        )

    # Validate and clean each Knowledge item
    validated_items = []
    for idx, item in enumerate(llm_response):
        try:
            cleaned_item = _validate_and_clean_knowledge_item(item, idx)
            validated_items.append(cleaned_item)
        except ValueError as e:
            logger.warning(f"Skipping Knowledge item {idx}: {str(e)}")
            continue

    # Apply limit (safety cap)
    if len(validated_items) > MAX_KNOWLEDGE_ITEMS_PER_MEMORY:
        logger.warning(f"Truncating {len(validated_items)} items to {MAX_KNOWLEDGE_ITEMS_PER_MEMORY}")
        validated_items = validated_items[:MAX_KNOWLEDGE_ITEMS_PER_MEMORY]

    # If all items were invalid, return empty
    if len(validated_items) == 0:
        logger.error(f"All {len(llm_response)} LLM-extracted items failed validation for Memory {memory_id}")
        return KnowledgeSynthesisLLMResult(
            llm_response=[],
            skip_reason=SKIP_REASON_NO_EXTRACTIONS,
            error="All LLM-extracted Knowledge items failed validation",
        )

    logger.info(f"Validated {len(validated_items)}/{len(llm_response)} Knowledge items for Memory {memory_id}")

    return KnowledgeSynthesisLLMResult(llm_response=validated_items)


# ============================================================================
# Validation & Cleaning
# ============================================================================

def _validate_and_clean_knowledge_item(item: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Validate and clean a single Knowledge item from LLM response.

    Checks:
    - Required fields present (knowledge_type, content, summary, topic)
    - knowledge_type is valid enum value
    - Content/summary length within bounds

    Raises:
        ValueError: If validation fails
    """
    # Check required fields
    required_fields = ["knowledge_type", "content", "summary"]
    for f in required_fields:
        if f not in item or not item[f]:
            raise ValueError(ERROR_REQUIRED_FIELD_MISSING.format(field=f))

    # Validate knowledge_type enum
    knowledge_type_str = item["knowledge_type"]
    if VALIDATE_ENUM_STRICT:
        try:
            KnowledgeType(knowledge_type_str)
        except ValueError:
            raise ValueError(ERROR_INVALID_KNOWLEDGE_TYPE.format(type=knowledge_type_str))

    # Validate content length
    content = str(item["content"]).strip()
    if len(content) < MIN_CONTENT_LENGTH:
        raise ValueError(f"Content too short ({len(content)} < {MIN_CONTENT_LENGTH}): {content[:50]}")

    # Truncate if too long
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH-3] + "..."

    # Validate summary length
    summary = str(item["summary"]).strip()
    if len(summary) < MIN_SUMMARY_LENGTH:
        raise ValueError(f"Summary too short ({len(summary)} < {MIN_SUMMARY_LENGTH}): {summary}")

    # Truncate if too long
    if len(summary) > MAX_SUMMARY_LENGTH:
        summary = summary[:MAX_SUMMARY_LENGTH-3] + "..."

    # Topic is optional but encouraged
    topic = item.get("topic", DEFAULT_TOPIC)
    if not topic or not topic.strip():
        topic = DEFAULT_TOPIC

    # Return cleaned item
    return {
        "knowledge_type": knowledge_type_str,
        "content": content,
        "summary": summary,
        "topic": topic.strip(),
    }
