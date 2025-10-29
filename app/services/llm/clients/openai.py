"""
OpenAI (GPT) LLM Client Implementation.

Features:
- Automatic retry with exponential backoff
- Rate limit handling
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

    def __init__(self):
        """Initialize OpenAI async client."""
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set in environment")

        self.client = openai.AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY
        )
        self.model = OPENAI_MODEL

    @retry(
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
        )),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3)
    )
    async def call(self, prompt: str) -> str:
        """
        Call OpenAI API with automatic retry.

        Args:
            prompt: Prompt text to send

        Returns:
            Raw response text from GPT
        """
        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  # Force JSON output
        )

        return response.choices[0].message.content
