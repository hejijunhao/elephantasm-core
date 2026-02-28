"""
Knowledge Synthesis Configuration

Constants for LLM settings, extraction limits, and workflow parameters.
"""
import os
from typing import Literal


# ============================================================================
# LLM Provider Selection (CHANGE THIS TO SWITCH PROVIDERS)
# ============================================================================

LLM_PROVIDER: Literal["anthropic", "openai"] = "anthropic"
"""LLM provider for knowledge extraction (anthropic or openai)"""

ANTHROPIC_MODEL = os.getenv("KNOWLEDGE_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
"""Anthropic model for knowledge synthesis"""

OPENAI_MODEL = os.getenv("KNOWLEDGE_OPENAI_MODEL", "gpt-5-2025-08-07")
"""OpenAI model for knowledge synthesis"""


# ============================================================================
# LLM Configuration (Default Parameters)
# ============================================================================

LLM_MAX_TOKENS = int(os.getenv("KNOWLEDGE_LLM_MAX_TOKENS", "2000"))
"""
Max tokens for knowledge extraction response.

Higher than Memory Synthesis (1024) because:
- Multi-output (array of Knowledge items)
- Each item has 4 fields (type, content, summary, topic)
- Rich Memories may produce 10+ Knowledge items
"""

LLM_TEMPERATURE = float(os.getenv("KNOWLEDGE_LLM_TEMPERATURE", "0.7"))
"""
Temperature for knowledge extraction.

0.7 = Balanced creativity/consistency
- High enough for semantic topic generation
- Low enough for accurate type classification
"""


# ============================================================================
# Extraction Limits & Quality Controls
# ============================================================================

MAX_KNOWLEDGE_ITEMS_PER_MEMORY = int(os.getenv("MAX_KNOWLEDGE_ITEMS_PER_MEMORY", "50"))
"""
Maximum Knowledge items to extract from a single Memory.

Prevents runaway extraction on very long Memories.
LLM response will be truncated if exceeds this limit.

Rationale:
- Typical Memory: 1-5 Knowledge items
- Rich Memory: 5-15 items
- 50 = Safety cap (likely indicates over-extraction)
"""

MIN_CONTENT_LENGTH = int(os.getenv("MIN_KNOWLEDGE_CONTENT_LENGTH", "10"))
"""
Minimum character length for Knowledge content field.

Filters out trivial extractions (e.g., "OK", "Yes").
LLM responses with content shorter than this are discarded.
"""

MAX_CONTENT_LENGTH = int(os.getenv("MAX_KNOWLEDGE_CONTENT_LENGTH", "1000"))
"""
Maximum character length for Knowledge content field.

Prevents overly verbose extractions (should be atomic).
Content longer than this is truncated with "..." suffix.
"""

MIN_SUMMARY_LENGTH = int(os.getenv("MIN_KNOWLEDGE_SUMMARY_LENGTH", "3"))
"""Minimum character length for Knowledge summary field"""

MAX_SUMMARY_LENGTH = int(os.getenv("MAX_KNOWLEDGE_SUMMARY_LENGTH", "200"))
"""Maximum character length for Knowledge summary field (display constraint)"""


# ============================================================================
# Topic Management
# ============================================================================

MAX_TOPIC_LENGTH = int(os.getenv("MAX_TOPIC_LENGTH", "100"))
"""Maximum character length for topic namespace"""

DEFAULT_TOPIC = "General"
"""Default topic if LLM doesn't specify (fallback)"""

NORMALIZE_TOPICS = os.getenv("NORMALIZE_TOPICS", "false").lower() == "true"
"""
Whether to normalize/cluster similar topics (future feature).

Examples:
- "User Info" + "User Information" → "User Information"
- "Architecture" + "System Architecture" → "System Architecture"

Default: false (accept LLM topics as-is)
"""


# ============================================================================
# Deduplication Strategy
# ============================================================================

DEDUPLICATION_STRATEGY: Literal["replace", "append", "skip"] = "replace"
"""
How to handle re-synthesis of same Memory:

- "replace": Delete existing Knowledge with source_id=memory_id, insert new (DEFAULT)
- "append": Keep existing, add new (may create duplicates)
- "skip": If Knowledge exists with source_id, skip synthesis entirely

Recommendation: "replace" ensures Knowledge evolves with better LLM/prompts.
"""


# ============================================================================
# Audit Logging
# ============================================================================

AUDIT_TRIGGERED_BY = "knowledge_synthesis_workflow"
"""Default value for triggered_by field in audit logs"""

AUDIT_ALL_MUTATIONS = os.getenv("AUDIT_ALL_KNOWLEDGE_MUTATIONS", "true").lower() == "true"
"""Whether to create audit logs for all Knowledge CREATE operations (default: true)"""


# ============================================================================
# Retry Configuration
# ============================================================================

DB_RETRY_MAX_ATTEMPTS = 3
"""Max retry attempts for database operations"""

DB_RETRY_INITIAL_INTERVAL = 1.0
"""Initial retry interval (seconds) for database operations"""

LLM_RETRY_MAX_ATTEMPTS = 3
"""Max retry attempts for LLM API calls"""

LLM_RETRY_INITIAL_INTERVAL = 2.0
"""Initial retry interval (seconds) for LLM API calls"""


# ============================================================================
# Scheduler Configuration (Future - Phase 7)
# ============================================================================

SYNTHESIS_JOB_INTERVAL_MINUTES = int(os.getenv("KNOWLEDGE_SYNTHESIS_JOB_INTERVAL_MINUTES", "5"))
"""
How often to run knowledge synthesis scheduler (default: every 5 minutes).

Scheduler queries for Memories without Knowledge and synthesizes them.
"""

SYNTHESIS_BATCH_SIZE = int(os.getenv("KNOWLEDGE_SYNTHESIS_BATCH_SIZE", "10"))
"""
Max Memories to synthesize per scheduler run.

Prevents overwhelming LLM API with backlog. Processes in batches.
"""


# ============================================================================
# Feature Flags
# ============================================================================

INCLUDE_SOURCE_EVENTS = os.getenv("INCLUDE_SOURCE_EVENTS_IN_PROMPT", "false").lower() == "true"
"""
Whether to include source Events in prompt for additional context.

Adds provenance info to help LLM extraction (future enhancement).
Default: false (use Memory content only)
"""

VALIDATE_ENUM_STRICT = os.getenv("VALIDATE_KNOWLEDGE_TYPE_STRICT", "true").lower() == "true"
"""
Whether to strictly validate knowledge_type against KnowledgeType enum.

If true: Invalid types (e.g., "UNKNOWN") are rejected
If false: Invalid types accepted but logged as warning

Default: true (strict validation)
"""


# ============================================================================
# Error Messages (Constants)
# ============================================================================

ERROR_MEMORY_NOT_FOUND = "Memory not found or deleted"
ERROR_INVALID_MEMORY_ID = "Invalid memory_id format (must be UUID)"
ERROR_LLM_RESPONSE_INVALID = "LLM response is not a valid JSON array"
ERROR_LLM_RESPONSE_EMPTY = "LLM returned empty array (no extractable knowledge)"
ERROR_REQUIRED_FIELD_MISSING = "Knowledge item missing required field: {field}"
ERROR_INVALID_KNOWLEDGE_TYPE = "Invalid knowledge_type: {type} (must be FACT/CONCEPT/METHOD/PRINCIPLE/EXPERIENCE)"
ERROR_DB_WRITE_FAILED = "Failed to persist Knowledge items to database"


# ============================================================================
# Skip Reasons (Constants)
# ============================================================================

SKIP_REASON_INVALID_MEMORY = "invalid_memory"
"""Memory not found or deleted (fetch_memory_node)"""

SKIP_REASON_NO_EXTRACTIONS = "no_extractions"
"""LLM returned empty array (synthesize_knowledge_node)"""

SKIP_REASON_ALREADY_SYNTHESIZED = "already_synthesized"
"""Knowledge exists for this Memory and deduplication strategy is 'skip'"""


# ============================================================================
# Validation
# ============================================================================

# Sanity check: Ensure max > min for length constraints
assert MAX_CONTENT_LENGTH > MIN_CONTENT_LENGTH, "MAX_CONTENT_LENGTH must be > MIN_CONTENT_LENGTH"
assert MAX_SUMMARY_LENGTH > MIN_SUMMARY_LENGTH, "MAX_SUMMARY_LENGTH must be > MIN_SUMMARY_LENGTH"
assert MAX_KNOWLEDGE_ITEMS_PER_MEMORY > 0, "MAX_KNOWLEDGE_ITEMS_PER_MEMORY must be positive"
assert LLM_MAX_TOKENS > 0, "LLM_MAX_TOKENS must be positive"
assert 0.0 <= LLM_TEMPERATURE <= 2.0, "LLM_TEMPERATURE must be between 0.0 and 2.0"
