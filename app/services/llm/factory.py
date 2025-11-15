"""
LLM Client Factory - Provider selection and instantiation.

Single point of configuration for switching between LLM providers.
"""
from .clients.base import BaseLLMClient
from .clients.anthropic import AnthropicClient
from .clients.openai import OpenAIClient
from app.workflows.memory_synthesis.config import LLM_PROVIDER


def get_llm_client() -> BaseLLMClient:
    """
    Factory function to get LLM client based on config.

    Provider determined by LLM_PROVIDER in config.py.

    Returns:
        LLM client instance (Anthropic or OpenAI)

    Raises:
        ValueError: If provider not recognized or API key missing
    """
    if LLM_PROVIDER == "anthropic":
        return AnthropicClient()
    elif LLM_PROVIDER == "openai":
        return OpenAIClient()
    else:
        raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}. Use 'anthropic' or 'openai'.")
