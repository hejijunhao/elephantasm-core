"""
Anthropic (Claude) LLM Client Implementation.

Features:
- Automatic retry with exponential backoff
- Rate limit handling
- Async API calls
"""
import anthropic
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type
)
from .base import BaseLLMClient
from app.workflows.memory_synthesis.config import (
    ANTHROPIC_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
)
from app.core.config import settings


class AnthropicClient(BaseLLMClient):
    """
    Anthropic Claude API client.

    Handles API communication with retry logic.
    Prompts provided by workflow-specific modules.
    """

    def __init__(self):
        """Initialize Claude async client."""
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        self.client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY
        )
        self.model = ANTHROPIC_MODEL

    @retry(
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3)
    )
    async def call(self, prompt: str) -> str:
        """
        Call Claude API with automatic retry.

        Args:
            prompt: Prompt text to send

        Returns:
            Raw response text from Claude
        """
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text
