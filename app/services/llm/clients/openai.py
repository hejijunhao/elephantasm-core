"""
OpenAI (GPT) LLM Client Implementation.

Features:
- Automatic retry with exponential backoff (3 attempts)
- Retries: rate limits, connection errors, timeouts, server errors (5xx)
- Exponential backoff: 1-10 seconds between retries
- Async API calls
- JSON mode support
"""
import openai
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type
)
from .base import BaseLLMClient
from app.workflows.memory_synthesis.config import (
    OPENAI_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
)
from app.core.config import settings


class OpenAIClient(BaseLLMClient):
    """
    OpenAI GPT API client.

    Handles API communication with retry logic.
    Prompts provided by workflow-specific modules.
    """

    def __init__(self, model: str | None = None):
        """Initialize OpenAI async + sync clients."""
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in environment")

        self.client = openai.AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY
        )
        self.sync_client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY
        )
        self.model = model or OPENAI_MODEL

    @retry(
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,  # 5xx errors when servers overloaded
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
        Call OpenAI API with automatic retry.

        Args:
            prompt: Prompt text to send
            temperature: LLM temperature (defaults to config value)
            max_tokens: Max tokens for response (defaults to config value)

        Returns:
            Raw response text from GPT
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens if max_tokens is not None else LLM_MAX_TOKENS,
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  # Force JSON output
        )

        return response.choices[0].message.content

    @retry(
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
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
        """Sync OpenAI API call for thread-pool contexts."""
        response = self.sync_client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens if max_tokens is not None else LLM_MAX_TOKENS,
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        return response.choices[0].message.content
