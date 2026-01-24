"""
Knowledge Synthesis Node

Calls LLM to extract Knowledge items from Memory.
Core intelligence node - transforms Memory into structured Knowledge (multi-output).

⚠️ CRITICAL: Validates LLM response structure and enforces quality controls.
"""
import logging
from uuid import UUID
from typing import Dict, Any, List
from langsmith import traceable
from ..state import KnowledgeSynthesisState

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
    ERROR_LLM_RESPONSE_EMPTY,
    ERROR_REQUIRED_FIELD_MISSING,
    ERROR_INVALID_KNOWLEDGE_TYPE,
    SKIP_REASON_NO_EXTRACTIONS,
    VALIDATE_ENUM_STRICT,
)
from ..prompts import build_knowledge_synthesis_prompt
from app.services.llm import get_llm_client
from app.models.database.knowledge import KnowledgeType


@traceable(name="synthesize_knowledge", tags=["llm", "synthesis", "critical", "multi_output"])
async def synthesize_knowledge_node(state: KnowledgeSynthesisState) -> dict:
    """
    Synthesize Knowledge items from Memory via LLM.

    Async node (LLM API call).
    Calls LLM with Memory content, parses JSON array response,
    validates structure and enforces quality controls.

    Args:
        state: Current workflow state with memory_data

    Returns:
        State updates:
        - llm_response: Array of Knowledge item dicts (may be empty)
        - skip_reason: "no_extractions" if empty array
        - error: Error message if LLM fails or response invalid

    Raises:
        No exceptions raised - errors captured in state
    """
    memory_data = state.get("memory_data")

    if not memory_data:
        return {
            "error": "No memory_data in state (fetch_memory_node failed?)",
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
        }

    # Build prompt from Memory data
    try:
        prompt = build_knowledge_synthesis_prompt(memory_data)
    except Exception as e:
        return {
            "error": f"Failed to build prompt: {str(e)}",
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
        }

    # Get LLM client (provider selected via config)
    llm_client = get_llm_client()

    # Call LLM with default parameters (automatic retry logic in client)
    memory_id = memory_data.get('id', 'unknown')
    logger.info(f"🧠 Calling LLM for Memory {memory_id} knowledge synthesis...")

    try:
        response_text = await llm_client.call(
            prompt,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS
        )
        logger.info(f"✅ LLM response received for Memory {memory_id} ({len(response_text)} chars)")
    except Exception as e:
        error_msg = f"LLM API call failed: {str(e)}"
        logger.error(f"❌ {error_msg} | Memory: {memory_id} | Exception: {type(e).__name__}")
        logger.debug(f"Full error details: {repr(e)}")
        return {
            "error": error_msg,
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
        }

    # Parse JSON response (expects array)
    try:
        llm_response = llm_client.parse_json_response(response_text)
    except Exception as e:
        return {
            "error": f"{ERROR_LLM_RESPONSE_INVALID}: {str(e)}",
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
        }

    # Validate response is array
    if not isinstance(llm_response, list):
        return {
            "error": f"{ERROR_LLM_RESPONSE_INVALID}: Expected array, got {type(llm_response).__name__}",
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
        }

    # Empty array is valid (minimal Memory with no extractable knowledge)
    if len(llm_response) == 0:
        return {
            "llm_response": [],
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
            "error": None,  # Clear any stale error from previous checkpoint
        }

    # Validate and clean each Knowledge item
    validated_items = []
    for idx, item in enumerate(llm_response):
        try:
            cleaned_item = _validate_and_clean_knowledge_item(item, idx)
            validated_items.append(cleaned_item)
        except ValueError as e:
            # Log validation error but continue with other items
            # (Don't fail entire extraction due to one bad item)
            logger.warning(f"⚠️  Skipping Knowledge item {idx}: {str(e)}")
            continue

    # Apply limit (safety cap)
    if len(validated_items) > MAX_KNOWLEDGE_ITEMS_PER_MEMORY:
        logger.warning(f"⚠️  Truncating {len(validated_items)} items to {MAX_KNOWLEDGE_ITEMS_PER_MEMORY}")
        validated_items = validated_items[:MAX_KNOWLEDGE_ITEMS_PER_MEMORY]

    # If all items were invalid, return empty
    if len(validated_items) == 0:
        logger.error(f"❌ All {len(llm_response)} LLM-extracted items failed validation for Memory {memory_id}")
        return {
            "llm_response": [],
            "skip_reason": SKIP_REASON_NO_EXTRACTIONS,
            "error": "All LLM-extracted Knowledge items failed validation",
        }

    logger.info(f"✅ Validated {len(validated_items)}/{len(llm_response)} Knowledge items for Memory {memory_id}")

    return {
        "llm_response": validated_items,
        "error": None,  # Clear any stale error from previous checkpoint
    }


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
    - Normalize optional fields

    Args:
        item: Knowledge item dict from LLM
        index: Item index in array (for error messages)

    Returns:
        Cleaned Knowledge item dict

    Raises:
        ValueError: If validation fails
    """
    # Check required fields
    required_fields = ["knowledge_type", "content", "summary"]
    for field in required_fields:
        if field not in item or not item[field]:
            raise ValueError(ERROR_REQUIRED_FIELD_MISSING.format(field=field))

    # Validate knowledge_type enum
    knowledge_type_str = item["knowledge_type"]
    if VALIDATE_ENUM_STRICT:
        try:
            # Try to create enum (validates it's a valid value)
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
