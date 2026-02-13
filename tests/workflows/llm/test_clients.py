"""
Tests for multi-provider LLM client (using mocks to avoid API calls).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm import (
    get_llm_client,
    AnthropicClient,
    OpenAIClient,
    BaseLLMClient
)


# ============================================================================
# Factory Tests
# ============================================================================

def test_get_llm_client_anthropic():
    """Test factory returns Anthropic client when configured."""
    with patch('app.services.llm.factory.LLM_PROVIDER', 'anthropic'), \
         patch('app.services.llm.clients.anthropic.anthropic.AsyncAnthropic'), \
         patch('app.services.llm.clients.anthropic.settings.ANTHROPIC_API_KEY', 'test-key'):
        client = get_llm_client()
        assert isinstance(client, AnthropicClient)


def test_get_llm_client_openai():
    """Test factory returns OpenAI client when configured."""
    with patch('app.services.llm.factory.LLM_PROVIDER', 'openai'), \
         patch('app.services.llm.clients.openai.openai.AsyncOpenAI'), \
         patch('app.services.llm.clients.openai.settings.OPENAI_API_KEY', 'test-key'):
        client = get_llm_client()
        assert isinstance(client, OpenAIClient)


@patch('app.services.llm.factory.LLM_PROVIDER', 'invalid')
def test_get_llm_client_invalid_provider():
    """Test factory raises on invalid provider."""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm_client()


# ============================================================================
# Anthropic Client Tests
# ============================================================================

@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic async client."""
    with patch('app.services.llm.clients.anthropic.anthropic.AsyncAnthropic') as mock:
        yield mock


@pytest.mark.asyncio
async def test_anthropic_call_success(mock_anthropic_client):
    """Test successful API call with Anthropic."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='{"summary": "User discussed API integration", "importance": 0.8}')
    ]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mock_anthropic_client.return_value = mock_client

    # Test API call
    with patch('app.services.llm.clients.anthropic.settings.ANTHROPIC_API_KEY', 'test-key'):
        llm_client = AnthropicClient()
        result = await llm_client.call("Test prompt")

        assert result == '{"summary": "User discussed API integration", "importance": 0.8}'


# ============================================================================
# OpenAI Client Tests
# ============================================================================

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI async client."""
    with patch('app.services.llm.clients.openai.openai.AsyncOpenAI') as mock:
        yield mock


@pytest.mark.asyncio
async def test_openai_call_success(mock_openai_client):
    """Test successful API call with OpenAI."""
    # Setup mock response
    mock_choice = MagicMock()
    mock_choice.message.content = '{"summary": "User asked about features", "importance": 0.7}'

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_openai_client.return_value = mock_client

    # Test API call
    with patch('app.services.llm.clients.openai.settings.OPENAI_API_KEY', 'test-key'):
        llm_client = OpenAIClient()
        result = await llm_client.call("Test prompt")

        assert result == '{"summary": "User asked about features", "importance": 0.7}'


# ============================================================================
# Shared Functionality Tests
# ============================================================================

@pytest.mark.asyncio
async def test_parse_json_response_raw_json(mock_anthropic_client):
    """Test parsing raw JSON response."""
    mock_anthropic_client.return_value = AsyncMock()

    with patch('app.services.llm.clients.anthropic.settings.ANTHROPIC_API_KEY', 'test-key'):
        llm_client = AnthropicClient()
        result = llm_client.parse_json_response('{"summary": "Test", "importance": 0.5}')

        assert result["summary"] == "Test"
        assert result["importance"] == 0.5


@pytest.mark.asyncio
async def test_parse_json_response_markdown_block(mock_anthropic_client):
    """Test parsing JSON from markdown code blocks."""
    mock_anthropic_client.return_value = AsyncMock()

    with patch('app.services.llm.clients.anthropic.settings.ANTHROPIC_API_KEY', 'test-key'):
        llm_client = AnthropicClient()
        result = llm_client.parse_json_response('```json\n{"summary": "Test", "importance": 0.5}\n```')

        assert result["summary"] == "Test"
        assert result["importance"] == 0.5


@pytest.mark.asyncio
async def test_parse_json_response_invalid_json(mock_anthropic_client):
    """Test that parser raises error on invalid JSON."""
    mock_anthropic_client.return_value = AsyncMock()

    with patch('app.services.llm.clients.anthropic.settings.ANTHROPIC_API_KEY', 'test-key'):
        llm_client = AnthropicClient()

        with pytest.raises(ValueError, match="Failed to parse LLM response"):
            llm_client.parse_json_response('This is not JSON')
