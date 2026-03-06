"""
Anthropic (Claude) LLM Client Implementation.

Features:
- Automatic retry with exponential backoff (3 attempts)
- Retries: rate limits, connection errors, timeouts, server errors (5xx)
- Exponential backoff: 1-10 seconds between retries
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

    def __init__(self, model: str | None = None):
        """Initialize Claude async + sync clients."""
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        self.client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY
        )
        self.sync_client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY
        )
        self.model = model or ANTHROPIC_MODEL

    @retry(
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,  # 5xx errors including 529 overload
        )),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3)
    )
    async def call(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None
    ) -> str:
        """
        Call Claude API with automatic retry.

        Args:
            prompt: Prompt text to send
            temperature: LLM temperature (defaults to config value)
            max_tokens: Max tokens for response (defaults to config value)

        Returns:
            Raw response text from Claude
        """
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens if max_tokens is not None else LLM_MAX_TOKENS,
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            system="Respond with valid JSON only. No preamble, no markdown fences, no explanation — just the JSON object or array.",
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text

    @retry(
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3)
    )
    def call_sync(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None
    ) -> str:
        """Sync Claude API call for thread-pool contexts."""
        response = self.sync_client.messages.create(
            model=self.model,
            max_tokens=max_tokens if max_tokens is not None else LLM_MAX_TOKENS,
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            system="Respond with valid JSON only. No preamble, no markdown fences, no explanation — just the JSON object or array.",
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text
