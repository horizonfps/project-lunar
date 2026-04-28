from __future__ import annotations
import asyncio
import inspect
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

import litellm

# Retry delays (seconds) for transient proxy/upstream failures.
# Total attempts = len(_PROXY_RETRY_DELAYS) + 1.
_PROXY_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.5)

logger = logging.getLogger(__name__)

# ── Token Debug Tracking ────────────────────────────────────────────
# Accumulates per-action stats across all LLM calls.
_call_log: list[dict] = []


def reset_call_log():
    """Reset the per-action call log. Call at the start of each action."""
    _call_log.clear()


def get_call_log() -> list[dict]:
    """Return accumulated LLM call stats for the current action."""
    return list(_call_log)


def get_call_summary() -> dict:
    """Return a summary of all LLM calls in the current action."""
    total_input = sum(c.get("input_tokens", 0) for c in _call_log)
    total_output = sum(c.get("output_tokens", 0) for c in _call_log)
    total_time = sum(c.get("elapsed_s", 0) for c in _call_log)
    return {
        "call_count": len(_call_log),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_time_s": round(total_time, 2),
        "calls": [
            {
                "caller": c.get("caller", "?"),
                "input_tokens": c.get("input_tokens", 0),
                "output_tokens": c.get("output_tokens", 0),
                "max_tokens": c.get("max_tokens", 0),
                "elapsed_s": c.get("elapsed_s", 0),
                "msg_count": c.get("msg_count", 0),
                "system_chars": c.get("system_chars", 0),
            }
            for c in _call_log
        ],
    }


def _get_caller() -> str:
    """Walk the stack to find the meaningful caller (skip llm_router frames)."""
    for frame_info in inspect.stack()[2:6]:
        module = frame_info.filename
        if "llm_router" not in module:
            fname = os.path.basename(module).replace(".py", "")
            return f"{fname}:{frame_info.function}:{frame_info.lineno}"
    return "unknown"


def _count_message_chars(messages: list[dict]) -> tuple[int, int]:
    """Return (system_chars, total_chars) from messages."""
    system_chars = 0
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            chars = sum(len(p.get("text", "")) for p in content if isinstance(p, dict))
        else:
            chars = len(content)
        total_chars += chars
        if msg.get("role") == "system":
            system_chars += chars
    return system_chars, total_chars


def _log_call(caller: str, messages: list[dict], max_tokens: int, response, elapsed: float):
    """Log a completed LLM call with token usage."""
    system_chars, total_chars = _count_message_chars(messages)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

    # Fallback: estimate from chars if usage not available
    if not input_tokens:
        input_tokens = total_chars // 4  # rough estimate

    entry = {
        "caller": caller,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "max_tokens": max_tokens,
        "elapsed_s": round(elapsed, 2),
        "msg_count": len(messages),
        "system_chars": system_chars,
    }
    _call_log.append(entry)
    logger.warning(
        "🔥 LLM CALL [%s] input=%d output=%d max=%d time=%.1fs msgs=%d sys_chars=%d",
        caller, input_tokens, output_tokens, max_tokens, elapsed,
        len(messages), system_chars,
    )


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


# Context window sizes (in tokens) per provider/model.
# Used to calculate dynamic context budgets.
_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek V4 (1M context)
    "deepseek/deepseek-v4-flash": 1_000_000,
    "deepseek/deepseek-v4-pro": 1_000_000,
    # Legacy aliases — map to DeepSeek-V4-Flash (non-thinking / thinking modes)
    "deepseek/deepseek-chat": 1_000_000,
    "deepseek/deepseek-reasoner": 1_000_000,
    # Anthropic — Claude 4.6 (1M context)
    "anthropic/claude-opus-4-6": 1_000_000,
    "anthropic/claude-sonnet-4-6": 1_000_000,
    # Anthropic — Claude 4.5 / 4.0 / Haiku (200k context)
    "anthropic/claude-haiku-4-5-20251001": 200_000,
    "anthropic/claude-haiku-4-5": 200_000,
    "anthropic/claude-sonnet-4-5-20250929": 200_000,
    "anthropic/claude-sonnet-4-5": 200_000,
    "anthropic/claude-opus-4-5-20251101": 200_000,
    "anthropic/claude-opus-4-5": 200_000,
    "anthropic/claude-opus-4-1-20250805": 200_000,
    "anthropic/claude-opus-4-1": 200_000,
    "anthropic/claude-sonnet-4-20250514": 200_000,
    "anthropic/claude-sonnet-4-0": 200_000,
    "anthropic/claude-opus-4-20250514": 200_000,
    "anthropic/claude-opus-4-0": 200_000,
    # OpenAI — GPT-5.4 (1M context)
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
    # OpenAI — legacy
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
}
_DEFAULT_CONTEXT_WINDOW = 200_000  # reasonable fallback


@dataclass
class LLMConfig:
    primary_provider: LLMProvider = LLMProvider.DEEPSEEK
    primary_model: str = "deepseek-v4-flash"
    fallback_provider: LLMProvider | None = None
    fallback_model: str | None = None
    temperature: float = 0.85
    max_tokens: int = 2000

    def get_context_window(self) -> int:
        """Return the context window size (tokens) for the current primary model."""
        model_key = (
            self.primary_model
            if self.primary_provider == LLMProvider.OPENAI
            else f"{self.primary_provider.value}/{self.primary_model}"
        )
        return _CONTEXT_WINDOWS.get(model_key, _DEFAULT_CONTEXT_WINDOW)


# When ANTHROPIC_PROXY_URL is set, Anthropic requests route through the
# Claude Max Proxy (uses Pro/Max subscription instead of API rate limits).
_ANTHROPIC_PROXY_URL = os.environ.get("ANTHROPIC_PROXY_URL", "")
_ANTHROPIC_PROXY_KEY = os.environ.get("ANTHROPIC_PROXY_KEY", "proxy")


class LLMRouter:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_model_string(self, provider: LLMProvider, model: str) -> str:
        if provider == LLMProvider.OPENAI:
            return model
        return f"{provider.value}/{model}"

    def _get_api_base(self, provider: LLMProvider) -> str | None:
        """Return custom api_base for providers that use a local proxy."""
        if provider == LLMProvider.ANTHROPIC and _ANTHROPIC_PROXY_URL:
            return _ANTHROPIC_PROXY_URL
        return None

    @staticmethod
    def _sanitize_messages_for_anthropic(messages: list[dict]) -> list[dict]:
        """Anthropic requires the first non-system message to have role=user.

        Legacy campaigns persisted the AI opening as a leading assistant
        message; drop any leading assistant messages so the request is
        accepted. The opening is now injected as system context, so no
        information is lost.
        """
        out: list[dict] = []
        seen_first_non_system = False
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                out.append(msg)
                continue
            if not seen_first_non_system and role == "assistant":
                continue
            seen_first_non_system = True
            out.append(msg)
        return out

    async def complete(self, messages: list[dict], **kwargs) -> str:
        caller = _get_caller()
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        api_base = self._get_api_base(self.config.primary_provider)
        call_kwargs = {**kwargs}
        if api_base:
            call_kwargs["api_base"] = api_base
            call_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
        if self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages = self._sanitize_messages_for_anthropic(messages)
        t0 = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=max_tokens,
                **call_kwargs,
            )
            _log_call(caller, messages, max_tokens, response, time.monotonic() - t0)
            return response.choices[0].message.content
        except Exception:
            if self.config.fallback_provider and self.config.fallback_model:
                fallback_model = self._build_model_string(
                    self.config.fallback_provider, self.config.fallback_model
                )
                fb_api_base = self._get_api_base(self.config.fallback_provider)
                fb_kwargs = {**kwargs}
                if fb_api_base:
                    fb_kwargs["api_base"] = fb_api_base
                    fb_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
                response = await litellm.acompletion(
                    model=fallback_model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    **fb_kwargs,
                )
                _log_call(caller, messages, max_tokens, response, time.monotonic() - t0)
                return response.choices[0].message.content
            raise

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        caller = _get_caller()
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        api_base = self._get_api_base(self.config.primary_provider)
        call_kwargs = {**kwargs}
        if self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages = self._sanitize_messages_for_anthropic(messages)
        if api_base:
            call_kwargs["api_base"] = api_base
            call_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
            # CLIProxyAPI streaming adds extra fields that confuse litellm's
            # SSE parser, so fall back to non-streaming and yield the result.
            # Retry on transient proxy/upstream failures so a single hiccup
            # doesn't surface the hardcoded English fallback to the player.
            t0 = time.monotonic()
            last_exc: Exception | None = None
            response = None
            total_attempts = len(_PROXY_RETRY_DELAYS) + 1
            for attempt in range(total_attempts):
                try:
                    response = await litellm.acompletion(
                        model=model,
                        messages=messages,
                        temperature=self.config.temperature,
                        max_tokens=max_tokens,
                        stream=False,
                        **call_kwargs,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "LLM proxy call failed (attempt %d/%d) [%s] err=%s: %s",
                        attempt + 1, total_attempts, caller, type(exc).__name__, exc,
                    )
                    if attempt < len(_PROXY_RETRY_DELAYS):
                        await asyncio.sleep(_PROXY_RETRY_DELAYS[attempt])
            if last_exc is not None:
                logger.error(
                    "LLM proxy call exhausted %d attempts [%s]; raising %s",
                    total_attempts, caller, type(last_exc).__name__, exc_info=last_exc,
                )
                raise last_exc
            _log_call(caller + "(stream→sync)", messages, max_tokens, response, time.monotonic() - t0)
            content = response.choices[0].message.content
            if content:
                yield content
            return
        t0 = time.monotonic()
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=max_tokens,
            stream=True,
            **call_kwargs,
        )
        output_chars = 0
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                output_chars += len(delta)
                yield delta
        # For streaming, estimate tokens from output chars
        system_chars, total_chars = _count_message_chars(messages)
        entry = {
            "caller": caller + "(stream)",
            "input_tokens": total_chars // 4,
            "output_tokens": output_chars // 4,
            "max_tokens": max_tokens,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "msg_count": len(messages),
            "system_chars": system_chars,
        }
        _call_log.append(entry)
        logger.warning(
            "🔥 LLM CALL [%s] input≈%d output≈%d max=%d time=%.1fs msgs=%d sys_chars=%d",
            entry["caller"], entry["input_tokens"], entry["output_tokens"],
            max_tokens, entry["elapsed_s"], len(messages), system_chars,
        )
