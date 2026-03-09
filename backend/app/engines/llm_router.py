from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

import litellm


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


@dataclass
class LLMConfig:
    primary_provider: LLMProvider = LLMProvider.DEEPSEEK
    primary_model: str = "deepseek-chat"
    fallback_provider: LLMProvider | None = None
    fallback_model: str | None = None
    temperature: float = 0.8
    max_tokens: int = 2000


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
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
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
