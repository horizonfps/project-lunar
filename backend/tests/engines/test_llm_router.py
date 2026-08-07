import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.engines.llm_router import (
    LLMRouter, LLMConfig, LLMProvider, _fold_system_into_user, _accepts_temperature,
)


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
    model = router._build_model_string(LLMProvider.OPENAI, "gpt-5.6-sol")
    assert model == "openai/gpt-5.6-sol"


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
    router.config.fallback_model = "gpt-5.6-sol"
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


@pytest.mark.asyncio
async def test_complete_reasoning_false_disables_deepseek_reasoning(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(
            messages=[{"role": "user", "content": "test"}], reasoning=False
        )
    _, call_kwargs = mock_acompletion.call_args
    assert call_kwargs.get("reasoning_effort") == "none"
    assert "reasoning" not in call_kwargs


@pytest.mark.asyncio
async def test_complete_without_reasoning_key_omits_reasoning_effort(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(messages=[{"role": "user", "content": "test"}])
    _, call_kwargs = mock_acompletion.call_args
    assert "reasoning_effort" not in call_kwargs
    assert "reasoning" not in call_kwargs


@pytest.mark.asyncio
async def test_complete_reasoning_false_anthropic_never_sends_reasoning_effort():
    config = LLMConfig(
        primary_provider=LLMProvider.ANTHROPIC,
        primary_model="claude-sonnet-4-6",
        temperature=0.85,
        max_tokens=2000,
    )
    router = LLMRouter(config)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(
            messages=[{"role": "user", "content": "test"}], reasoning=False
        )
    _, call_kwargs = mock_acompletion.call_args
    assert "reasoning_effort" not in call_kwargs


@pytest.mark.asyncio
async def test_complete_empty_output_logs_error(router, caplog):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=""), finish_reason="length")]
    mock_response.usage = MagicMock(
        prompt_tokens=10, completion_tokens=64, completion_tokens_details=MagicMock(reasoning_tokens=64)
    )
    with patch("app.engines.llm_router.litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        with caplog.at_level("ERROR"):
            await router.complete(messages=[{"role": "user", "content": "test"}])
    messages = [r.getMessage() for r in caplog.records]
    assert any("EMPTY OUTPUT" in m for m in messages)
    assert any("[" in m and "]" in m for m in messages)


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


@pytest.mark.asyncio
async def test_orchestrator_flag_without_orchestrator_model_uses_primary(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(messages=[{"role": "user", "content": "test"}])
        normal_model = mock_acompletion.call_args.kwargs["model"]
        await router.complete(messages=[{"role": "user", "content": "test"}], orchestrator=True)
        orchestrator_model = mock_acompletion.call_args.kwargs["model"]
    assert normal_model == orchestrator_model


@pytest.mark.asyncio
async def test_orchestrator_flag_with_orchestrator_model_configured():
    config = LLMConfig(
        primary_provider=LLMProvider.ANTHROPIC,
        primary_model="claude-sonnet-5",
        orchestrator_model="claude-opus-5",
        temperature=0.85,
        max_tokens=2000,
    )
    router = LLMRouter(config)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(
            messages=[{"role": "user", "content": "test"}], orchestrator=True
        )
        assert mock_acompletion.call_args.kwargs["model"] == "anthropic/claude-opus-5"
        await router.complete(messages=[{"role": "user", "content": "test"}])
        assert mock_acompletion.call_args.kwargs["model"] == "anthropic/claude-sonnet-5"


@pytest.mark.asyncio
async def test_orchestrator_kwarg_not_forwarded_to_acompletion(router):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(
            messages=[{"role": "user", "content": "test"}], orchestrator=True
        )
    _, call_kwargs = mock_acompletion.call_args
    assert "orchestrator" not in call_kwargs


def test_get_context_window_claude_5_without_orchestrator_model():
    config = LLMConfig(
        primary_provider=LLMProvider.ANTHROPIC,
        primary_model="claude-sonnet-5",
    )
    assert config.get_context_window() == 1_000_000


def test_get_context_window_claude_5_with_orchestrator_model():
    config = LLMConfig(
        primary_provider=LLMProvider.ANTHROPIC,
        primary_model="deepseek-v4-flash",
        orchestrator_model="claude-opus-5",
    )
    assert config.get_context_window() == 1_000_000


def test_accepts_temperature_false_for_claude_opus_5():
    assert _accepts_temperature("anthropic/claude-opus-5") is False


def test_get_context_window_gpt_5_6_sol():
    config = LLMConfig(
        primary_provider=LLMProvider.OPENAI,
        primary_model="gpt-5.6-sol",
    )
    assert config.get_context_window() == 372_000


def test_accepts_temperature_false_for_gpt_5_6_sol():
    assert _accepts_temperature("openai/gpt-5.6-sol") is False


@pytest.mark.asyncio
async def test_openai_proxy_uses_provider_specific_base_and_key():
    config = LLMConfig(
        primary_provider=LLMProvider.OPENAI,
        primary_model="gpt-5.6-sol",
        temperature=0.85,
        max_tokens=2000,
    )
    router = LLMRouter(config)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router._OPENAI_PROXY_URL", "http://127.0.0.1:48319/v1"), \
            patch("app.engines.llm_router._OPENAI_PROXY_KEY", "openai-proxy-key"), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        result = await router.complete(messages=[
            {"role": "user", "content": "test"},
        ])
    assert result == "ok"
    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-5.6-sol"
    assert call_kwargs["api_base"] == "http://127.0.0.1:48319/v1"
    assert call_kwargs["api_key"] == "openai-proxy-key"
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_openai_without_proxy_uses_direct_provider_configuration():
    config = LLMConfig(
        primary_provider=LLMProvider.OPENAI,
        primary_model="gpt-5.6-sol",
    )
    router = LLMRouter(config)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router._OPENAI_PROXY_URL", ""), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(messages=[{"role": "user", "content": "test"}])
    call_kwargs = mock_acompletion.call_args.kwargs
    assert "api_base" not in call_kwargs
    assert "api_key" not in call_kwargs


@pytest.mark.asyncio
async def test_openai_cached_system_is_flattened_for_proxy():
    config = LLMConfig(
        primary_provider=LLMProvider.OPENAI,
        primary_model="gpt-5.6-sol",
    )
    router = LLMRouter(config)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_acompletion = AsyncMock(return_value=mock_response)
    with patch("app.engines.llm_router._OPENAI_PROXY_URL", "http://127.0.0.1:48319/v1"), \
            patch("app.engines.llm_router.litellm.acompletion", new=mock_acompletion):
        await router.complete(messages=[
            {"role": "system", "content": [
                {"type": "text", "text": "part one"},
                {"type": "text", "text": "part two"},
            ]},
            {"role": "user", "content": "test"},
        ])
    sent_messages = mock_acompletion.call_args.kwargs["messages"]
    assert sent_messages[0] == {
        "role": "system",
        "content": "part one\npart two",
    }
