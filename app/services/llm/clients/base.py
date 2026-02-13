"""
Base LLM Client - Abstract interface for multi-provider support.

Defines generic interface for calling LLM APIs and parsing responses.
Provider-specific implementations in anthropic.py and openai.py.
"""
import json
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM clients.

    Separates infrastructure (API calls) from domain logic (prompts).
    """

    @abstractmethod
    async def call(self, prompt: str) -> str:
        """
        Generic LLM call with provider-specific implementation.

        Args:
            prompt: Prompt text to send to LLM

        Returns:
            Raw text response from LLM

        Raises:
            Provider-specific exceptions (handled by retry decorator)
        """
        pass

    def parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse LLM response into structured data.

        Handles both raw JSON and markdown code blocks.
        Shared across all providers.

        Args:
            response_text: Raw LLM response text

        Returns:
            Parsed JSON dict

        Raises:
            ValueError: If response is not valid JSON
        """
        text = response_text.strip()

        # Extract JSON from markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        # Parse JSON
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\n\nResponse:\n{response_text}")

        return data
