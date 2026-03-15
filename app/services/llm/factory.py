"""
LLM Client Factory - Provider selection and instantiation.

Single point of configuration for switching between LLM providers.
"""
from .clients.base import BaseLLMClient
from .clients.anthropic import AnthropicClient
from .clients.openai import OpenAIClient
from app.workflows.memory_synthesis.config import LLM_PROVIDER


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
) -> BaseLLMClient:
    """
    Factory function to get LLM client.

    Args:
        provider: Override provider (defaults to LLM_PROVIDER from synthesis config)
        model: Override model (defaults to provider's config default)

    Returns:
        LLM client instance (Anthropic or OpenAI)

    Raises:
        ValueError: If provider not recognized or API key missing
    """
    p = provider or LLM_PROVIDER
    if p == "anthropic":
        return AnthropicClient(model=model)
    elif p == "openai":
        return OpenAIClient(model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {p}. Use 'anthropic' or 'openai'.")
