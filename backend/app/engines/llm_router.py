from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

import litellm


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


# Context window sizes (in tokens) per provider/model.
# Used to calculate dynamic context budgets.
_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek (128k context)
    "deepseek/deepseek-chat": 128_000,
    "deepseek/deepseek-reasoner": 128_000,
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
    primary_model: str = "deepseek-chat"
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


class LLMRouter:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_model_string(self, provider: LLMProvider, model: str) -> str:
        if provider == LLMProvider.OPENAI:
            return model
        return f"{provider.value}/{model}"

    async def complete(self, messages: list[dict], **kwargs) -> str:
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return response.choices[0].message.content
        except Exception:
            if self.config.fallback_provider and self.config.fallback_model:
                fallback_model = self._build_model_string(
                    self.config.fallback_provider, self.config.fallback_model
                )
                response = await litellm.acompletion(
                    model=fallback_model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    **kwargs,
                )
                return response.choices[0].message.content
            raise

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
