"""
Memory Synthesis Configuration

Constants for accumulation scoring, thresholds, and LLM settings.
"""
import os
from typing import Literal
from app.core.config import settings


# ============================================================================
# LLM Provider Selection (CHANGE THIS TO SWITCH PROVIDERS)
# ============================================================================

LLM_PROVIDER: Literal["anthropic", "openai"] = "anthropic"

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")


# ============================================================================
# Shared LLM Configuration
# ============================================================================

LLM_MAX_TOKENS = int(os.getenv("SYNTHESIS_LLM_MAX_TOKENS", "1024"))
"""Max tokens for synthesis response"""

LLM_TEMPERATURE = float(os.getenv("SYNTHESIS_LLM_TEMPERATURE", "0.7"))
"""Temperature for synthesis (0.7 = balanced creativity/consistency)"""


# ============================================================================
# Accumulation Score Weights
# ============================================================================

# Composite score formula:
#   score = (hours × TIME_WEIGHT) + (events × EVENT_WEIGHT) + (tokens × TOKEN_WEIGHT)

TIME_WEIGHT = float(os.getenv("SYNTHESIS_TIME_WEIGHT", "1.0"))
"""Weight for time component (1.0 = 1 point per hour)"""

EVENT_WEIGHT = float(os.getenv("SYNTHESIS_EVENT_WEIGHT", "0.5"))
"""Weight for event count (0.5 = 1 point per 2 events)"""

TOKEN_WEIGHT = float(os.getenv("SYNTHESIS_TOKEN_WEIGHT", "0.0003"))
"""Weight for token count (0.0003 = 1 point per ~3,333 tokens)"""


# ============================================================================
# Synthesis Threshold
# ============================================================================

SYNTHESIS_THRESHOLD = float(os.getenv("SYNTHESIS_THRESHOLD", "10.0"))
"""
Minimum accumulation score to trigger synthesis.

Example scores:
- 10 hours + 0 events = 10.0 (triggers)
- 5 hours + 10 events = 10.0 (triggers)
- 2 hours + 5 events + 10k tokens = 10.0 (triggers)
"""


# ============================================================================
# Concurrency & Rate Limiting
# ============================================================================

LLM_CONCURRENCY_LIMIT = int(os.getenv("LLM_CONCURRENCY_LIMIT", "50"))
"""Max concurrent LLM API calls (rate limiting)"""


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
# Scheduler Configuration
# ============================================================================

SYNTHESIS_JOB_INTERVAL_HOURS = int(os.getenv("SYNTHESIS_JOB_INTERVAL_HOURS", "1"))
"""How often to run synthesis job (hourly by default)"""
