import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.engines.llm_router import LLMRouter, LLMConfig, LLMProvider, _fold_system_into_user


@pytest.fixture
def config():
    return LLMConfig(
        primary_provider=LLMProvider.DEEPSEEK,
        primary_model="deepseek-v4-flash",
        temperature=0.85,
        max_tokens=2000,
    )


@pytest.fixture
def router(config):
    return LLMRouter(config)


def test_build_deepseek_model_string(router):
    model = router._build_model_string(LLMProvider.DEEPSEEK, "deepseek-v4-flash")
    assert model == "deepseek/deepseek-v4-flash"


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


@pytest.fixture
def anthropic_config():
    return LLMConfig(
        primary_provider=LLMProvider.ANTHROPIC,
        primary_model="claude-sonnet-4-6",
        temperature=0.85,
        max_tokens=2000,
    )


@pytest.fixture
def anthropic_router(anthropic_config):
    return LLMRouter(anthropic_config)


@pytest.mark.asyncio
async def test_anthropic_with_proxy_folds_system_into_user(anthropic_router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router._ANTHROPIC_PROXY_URL", "http://localhost:8318"), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await anthropic_router.complete(messages=[
            {"role": "system", "content": "MARCADOR_XYZ"},
            {"role": "user", "content": "oi"},
        ])
    sent_messages = mock_acompletion.call_args.kwargs["messages"]
    assert not any(m.get("role") == "system" for m in sent_messages)
    first = sent_messages[0]
    assert first["role"] == "user"
    assert "MARCADOR_XYZ" in json_dump_content(first["content"])


@pytest.mark.asyncio
async def test_deepseek_messages_unchanged(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    original = [
        {"role": "system", "content": "MARCADOR_XYZ"},
        {"role": "user", "content": "oi"},
    ]
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(messages=list(original))
    sent_messages = mock_acompletion.call_args.kwargs["messages"]
    assert sent_messages == original


@pytest.mark.asyncio
async def test_anthropic_without_proxy_messages_unchanged(anthropic_router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    original = [
        {"role": "system", "content": "MARCADOR_XYZ"},
        {"role": "user", "content": "oi"},
    ]
    with patch("app.engines.llm_router._ANTHROPIC_PROXY_URL", ""), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await anthropic_router.complete(messages=list(original))
    sent_messages = mock_acompletion.call_args.kwargs["messages"]
    assert sent_messages == original


@pytest.mark.asyncio
async def test_anthropic_long_system_gets_cache_control_and_headers(anthropic_router):
    # A folded block >= 5000 chars carries cache_control, which routes through the
    # anthropic SDK path (litellm strips content-block cache_control), so mock the SDK client.
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="text", text="ok")]
    mock_msg.usage = MagicMock(input_tokens=10, output_tokens=5,
                                cache_read_input_tokens=0, cache_creation_input_tokens=0)
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)
    long_system = "A" * 6000
    with patch("app.engines.llm_router._ANTHROPIC_PROXY_URL", "http://localhost:8318"), \
            patch("app.engines.llm_router._get_anthropic_client", return_value=mock_client):
        await anthropic_router.complete(messages=[
            {"role": "system", "content": long_system},
            {"role": "user", "content": "oi"},
        ])
    sent_messages = mock_client.messages.create.call_args.kwargs["messages"]
    assert not any(m.get("role") == "system" for m in sent_messages)
    block = sent_messages[0]["content"][0]
    assert block.get("cache_control") == {"type": "ephemeral", "ttl": "1h"}
    extra_headers = mock_client.messages.create.call_args.kwargs["extra_headers"]
    assert "anthropic-beta" in extra_headers


@pytest.mark.asyncio
async def test_anthropic_short_system_no_cache_control(anthropic_router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    short_system = "A" * 200
    with patch("app.engines.llm_router._ANTHROPIC_PROXY_URL", "http://localhost:8318"), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await anthropic_router.complete(messages=[
            {"role": "system", "content": short_system},
            {"role": "user", "content": "oi"},
        ])
    sent_messages = mock_acompletion.call_args.kwargs["messages"]
    block = sent_messages[0]["content"][0]
    assert "cache_control" not in block


def json_dump_content(content):
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def test_fold_system_into_user_with_block_list_content():
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]},
        {"role": "user", "content": "hi"},
    ]
    folded, cached = _fold_system_into_user(messages)
    assert not cached
    text = folded[0]["content"][0]["text"]
    assert "part one" in text
    assert "part two" in text
