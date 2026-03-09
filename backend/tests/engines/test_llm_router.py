import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.engines.llm_router import LLMRouter, LLMConfig, LLMProvider


@pytest.fixture
def config():
    return LLMConfig(
        primary_provider=LLMProvider.DEEPSEEK,
        primary_model="deepseek-chat",
        temperature=0.8,
        max_tokens=2000,
    )


@pytest.fixture
def router(config):
    return LLMRouter(config)


def test_build_deepseek_model_string(router):
    model = router._build_model_string(LLMProvider.DEEPSEEK, "deepseek-chat")
    assert model == "deepseek/deepseek-chat"


def test_build_openai_model_string(router):
    model = router._build_model_string(LLMProvider.OPENAI, "gpt-4o")
    assert model == "gpt-4o"


def test_build_anthropic_model_string(router):
    model = router._build_model_string(LLMProvider.ANTHROPIC, "claude-sonnet-4-6")
    assert model == "anthropic/claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_complete_returns_text(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Once upon a time..."))]
    with patch("app.engines.llm_router.litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await router.complete(messages=[{"role": "user", "content": "Tell a story"}])
    assert result == "Once upon a time..."


@pytest.mark.asyncio
async def test_complete_uses_fallback_on_error(router):
    router.config.fallback_provider = LLMProvider.OPENAI
    router.config.fallback_model = "gpt-4o"
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Fallback response"))]
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Primary provider failed")
        return mock_response

    with patch("app.engines.llm_router.litellm.acompletion", side_effect=side_effect):
        result = await router.complete(messages=[{"role": "user", "content": "test"}])
    assert result == "Fallback response"
    assert call_count == 2
