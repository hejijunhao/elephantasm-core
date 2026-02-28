"""
Base LLM Client - Abstract interface for multi-provider support.

Defines generic interface for calling LLM APIs and parsing responses.
Provider-specific implementations in anthropic.py and openai.py.
"""
import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM clients.

    Separates infrastructure (API calls) from domain logic (prompts).
    """

    @abstractmethod
    async def call(self, prompt: str) -> str:
        """
        Async LLM call with provider-specific implementation.

        Args:
            prompt: Prompt text to send to LLM

        Returns:
            Raw text response from LLM

        Raises:
            Provider-specific exceptions (handled by retry decorator)
        """
        pass

    @abstractmethod
    def call_sync(self, prompt: str) -> str:
        """
        Sync LLM call for use in thread-pool contexts (e.g. Dreamer).

        Avoids asyncio.run() event loop lifecycle issues when called from
        threads that don't own an event loop.

        Args:
            prompt: Prompt text to send to LLM

        Returns:
            Raw text response from LLM
        """
        pass

    def parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse LLM response into structured data.

        Extraction priority:
        1. Raw JSON (response is already valid JSON)
        2. Markdown code blocks (```json ... ``` or ``` ... ```)
        3. First JSON object or array found in the text

        Args:
            response_text: Raw LLM response text

        Returns:
            Parsed JSON dict or list

        Raises:
            ValueError: If no valid JSON can be extracted
        """
        text = response_text.strip()

        # 1. Try parsing the full text as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Try extracting from markdown code blocks
        if "```json" in text:
            block = text.split("```json")[1].split("```")[0]
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                pass
        elif "```" in text:
            block = text.split("```")[1].split("```")[0]
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                pass

        # 3. Extract first JSON object {...} or array [...] from text
        match = re.search(r'[\[{]', text)
        if match:
            start = match.start()
            # Try parsing from the first bracket to the end, trimming
            # progressively until we find valid JSON
            candidate = text[start:]
            # Find matching closing bracket
            open_char = candidate[0]
            close_char = ']' if open_char == '[' else '}'
            last_close = candidate.rfind(close_char)
            if last_close != -1:
                try:
                    return json.loads(candidate[:last_close + 1])
                except json.JSONDecodeError:
                    pass

        raise ValueError(
            f"Failed to parse LLM response as JSON.\n\nResponse:\n{response_text}"
        )
