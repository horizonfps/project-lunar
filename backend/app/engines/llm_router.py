from __future__ import annotations
import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import AsyncIterator

import litellm

# Forensic dump of every LLM call for cost / cache investigation.
# Activate by setting LUNAR_DUMP_LLM_CALLS=1 — writes one JSON per call to
# logs/llm_calls/<utc-ts>_<short-id>_<caller>.json. Files contain the full
# request (messages, model, max_tokens) + response + timing, so we can
# reconstruct exactly what every provider received without depending on
# upstream dashboards.
_DUMP_ENABLED = os.environ.get("LUNAR_DUMP_LLM_CALLS", "0") == "1"
_DUMP_DIR = Path(os.environ.get("LUNAR_DUMP_LLM_DIR", "logs/llm_calls"))

# Devtools trace: capture the full input (prompt sections) + output text of every
# LLM call so the frontend panel can show exactly what each turn sent. Heavier than
# the token counters, so it is gated and per-section capped.
_TRACE_ENABLED = os.environ.get("LUNAR_DEVTOOLS_TRACE", "1") == "1"
_TRACE_MAX_CHARS = int(os.environ.get("LUNAR_DEVTOOLS_TRACE_MAX", "20000"))

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
    total_cache_read = sum(c.get("cache_read", 0) for c in _call_log)
    total_cache_creation = sum(c.get("cache_creation", 0) for c in _call_log)
    total_time = sum(c.get("elapsed_s", 0) for c in _call_log)
    return {
        "call_count": len(_call_log),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_creation,
        "total_tokens": total_input + total_output,
        "total_time_s": round(total_time, 2),
        "calls": [
            {
                "caller": c.get("caller", "?"),
                "input_tokens": c.get("input_tokens", 0),
                "output_tokens": c.get("output_tokens", 0),
                "cache_read": c.get("cache_read", 0),
                "cache_creation": c.get("cache_creation", 0),
                "max_tokens": c.get("max_tokens", 0),
                "elapsed_s": c.get("elapsed_s", 0),
                "msg_count": c.get("msg_count", 0),
                "system_chars": c.get("system_chars", 0),
            }
            for c in _call_log
        ],
    }


def get_call_trace() -> list[dict]:
    """Full per-call trace (input sections + output + usage) for the devtools panel."""
    trace: list[dict] = []
    for i, c in enumerate(_call_log):
        trace.append({
            "seq": i + 1,
            "tag": _trace_tag(c.get("caller", "")),
            "label": c.get("caller", "?"),
            "model": c.get("model", ""),
            "instructions_chars": c.get("system_chars", 0),
            "elapsed_s": c.get("elapsed_s", 0),
            "usage": {
                "input": c.get("input_tokens", 0),
                "output": c.get("output_tokens", 0),
                "cache_read": c.get("cache_read", 0),
                "cache_creation": c.get("cache_creation", 0),
                "reasoning": c.get("reasoning_tokens", 0),
            },
            "input": c.get("input", []),
            "output": c.get("output", ""),
        })
    return trace


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


def _serialize_messages(messages: list[dict]) -> list[dict]:
    """Return a deep-copied, JSON-safe view of the LLM messages."""
    out: list[dict] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = [
                {k: v for k, v in part.items()} if isinstance(part, dict) else str(part)
                for part in content
            ]
        out.append({"role": msg.get("role", ""), "content": content})
    return out


def _trace_sections(messages: list[dict]) -> list[dict]:
    """Render each message into a titled, length-capped section for the devtools panel."""
    sections: list[dict] = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        cached = False
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("cache_control"):
                        cached = True
                    parts.append(part.get("text", "") or json.dumps(part, ensure_ascii=False))
                else:
                    parts.append(str(part))
            body = "\n".join(parts)
        else:
            body = str(content)
        truncated = len(body) > _TRACE_MAX_CHARS
        if truncated:
            body = body[:_TRACE_MAX_CHARS] + f"\n… [+{len(body) - _TRACE_MAX_CHARS} chars truncated]"
        title = f"#{i} · {role}" + (" · cache_control" if cached else "")
        sections.append({"title": title, "body": body, "truncated": truncated})
    return sections


def _trace_tag(caller: str) -> str:
    """Short semantic tag from a caller string for the panel badge."""
    head = caller.split(":", 1)[0].split("(", 1)[0]
    return head.replace("_engine", "") or "llm"


def _extract_response_text(response) -> str:
    """Pull the assistant text from a litellm response (best-effort)."""
    try:
        choice = response.choices[0]
        msg = getattr(choice, "message", None)
        if msg is not None:
            return getattr(msg, "content", "") or ""
        delta = getattr(choice, "delta", None)
        if delta is not None:
            return getattr(delta, "content", "") or ""
    except Exception:
        pass
    return ""


def _cache_tokens(usage) -> tuple[int, int]:
    """(cache_read, cache_creation) from a litellm/Anthropic usage object.

    Zero until FASE 2 wires cache_control; the fields make cache hits measurable."""
    if usage is None:
        return 0, 0
    read = getattr(usage, "cache_read_input_tokens", None)
    if read is None:
        details = getattr(usage, "prompt_tokens_details", None)
        read = getattr(details, "cached_tokens", 0) if details else 0
    creation = getattr(usage, "cache_creation_input_tokens", 0)
    return int(read or 0), int(creation or 0)


def _dump_call(
    caller: str,
    model: str,
    messages: list[dict],
    max_tokens: int,
    response_text: str,
    input_tokens: int,
    output_tokens: int,
    elapsed: float,
    streamed: bool,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> None:
    """If enabled, write a full record of this LLM call to disk."""
    if not _DUMP_ENABLED:
        return
    try:
        _DUMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S_%f")[:-3]
        short_id = uuid.uuid4().hex[:6]
        safe_caller = caller.replace(":", "_").replace("/", "_")[:60]
        path = _DUMP_DIR / f"{ts}_{short_id}_{safe_caller}.json"
        record = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "caller": caller,
            "model": model,
            "max_tokens": max_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
            "elapsed_s": round(elapsed, 3),
            "streamed": streamed,
            "msg_count": len(messages),
            "messages": _serialize_messages(messages),
            "response_text": response_text,
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to dump LLM call to disk")


def _log_call(caller: str, messages: list[dict], max_tokens: int, response, elapsed: float, model: str = ""):
    """Log a completed LLM call with token usage."""
    system_chars, total_chars = _count_message_chars(messages)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cache_read, cache_creation = _cache_tokens(usage)

    try:
        finish_reason = getattr(response.choices[0], "finish_reason", "") or ""
    except Exception:
        finish_reason = ""
    try:
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
    except Exception:
        reasoning_tokens = 0

    # Fallback: estimate from chars if usage not available
    if not input_tokens:
        input_tokens = total_chars // 4  # rough estimate

    response_text = _extract_response_text(response)

    entry = {
        "caller": caller,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "max_tokens": max_tokens,
        "elapsed_s": round(elapsed, 2),
        "msg_count": len(messages),
        "system_chars": system_chars,
        "finish_reason": finish_reason,
        "reasoning_tokens": reasoning_tokens,
    }
    if _TRACE_ENABLED:
        entry["input"] = _trace_sections(messages)
        entry["output"] = response_text
    _call_log.append(entry)
    logger.warning(
        "🔥 LLM CALL [%s] input=%d output=%d cache_r=%d cache_w=%d max=%d time=%.1fs msgs=%d sys_chars=%d",
        caller, input_tokens, output_tokens, cache_read, cache_creation, max_tokens, elapsed,
        len(messages), system_chars,
    )
    if not response_text.strip():
        logger.error(
            "🚨 LLM EMPTY OUTPUT [%s] model=%s max_tokens=%d finish_reason=%s "
            "output_tokens=%d reasoning_tokens=%d — model spent the budget before writing an answer",
            caller, model, max_tokens, finish_reason, output_tokens, reasoning_tokens,
        )
    _dump_call(
        caller=caller,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        response_text=response_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed=elapsed,
        streamed=False,
        cache_read=cache_read,
        cache_creation=cache_creation,
    )


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


def _reasoning_kwargs(provider: LLMProvider, reasoning: bool) -> dict:
    """DeepSeek V4 counts reasoning against max_tokens; disable it for mechanical calls."""
    if reasoning or provider != LLMProvider.DEEPSEEK:
        return {}
    return {"reasoning_effort": "none"}


# Context window sizes (in tokens) per provider/model.
# Used to calculate dynamic context budgets.
_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek V4 (1M context)
    "deepseek/deepseek-v4-flash": 1_000_000,
    "deepseek/deepseek-v4-pro": 1_000_000,
    # Legacy aliases — map to DeepSeek-V4-Flash (non-thinking / thinking modes)
    "deepseek/deepseek-chat": 1_000_000,
    "deepseek/deepseek-reasoner": 1_000_000,
    # Anthropic Claude 5 (1M context)
    "anthropic/claude-opus-5": 1_000_000,
    "anthropic/claude-sonnet-5": 1_000_000,
    # Anthropic Claude 4.6 (1M context)
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

# FASE 2 prompt caching transport.
# Narrator emits its system prompt as text blocks with cache_control on the stable
# zones. On the Anthropic (CLIProxyAPI) path those blocks are cloaked into the first
# user message so caching survives the proxy's OAuth handling; the extended-cache-ttl
# beta header enables the 1h TTL. Other providers get a flat system string.
_CACHE_HEADERS = {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
_CLOAK_TAG = "narrator-instructions"

# Models that 400 on non-default sampling params (temperature/top_p/top_k).
# Opus 4.6 and Sonnet 4.6 still accept them.
_NO_SAMPLING_MODELS = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def _accepts_temperature(model: str) -> bool:
    """False for models that reject sampling params. Handles the 'provider/model' form."""
    bare = model.split("/")[-1]
    return not any(bare.startswith(p) for p in _NO_SAMPLING_MODELS)


def _is_cached_form(messages: list[dict]) -> bool:
    """True when messages carry the FASE 2 cached form: a leading system message
    whose content is a list of text blocks (zones)."""
    return bool(messages) and messages[0].get("role") == "system" and isinstance(
        messages[0].get("content"), list
    )


def _cloak_messages_for_anthropic(messages: list[dict]) -> list[dict]:
    """Move the leading system blocks into a cloaked user message, preserving
    cache_control. Block 0 is wrapped in <narrator-instructions> tags."""
    system = messages[0]
    blocks = system.get("content", [])
    cloaked: list[dict] = []
    for i, b in enumerate(blocks):
        text = b.get("text", "")
        if i == 0:
            text = f"<{_CLOAK_TAG}>\n{text}\n</{_CLOAK_TAG}>"
        new_block: dict = {"type": "text", "text": text}
        if "cache_control" in b:
            new_block["cache_control"] = b["cache_control"]
        cloaked.append(new_block)
    return [{"role": "user", "content": cloaked}] + messages[1:]


_SYSTEM_CLOAK_TAG = "system-instructions"
_SYSTEM_CACHE_MIN_CHARS = 5000
_SYSTEM_CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}


def _fold_system_into_user(messages: list[dict]) -> tuple[list[dict], bool]:
    """Proxy OAuth mode replaces the system field, so carry system text as a leading
    user block instead. Returns (messages, cached) — cached is True when the folded
    block got cache_control."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    if not system_msgs:
        return messages, False
    parts: list[str] = []
    for m in system_msgs:
        content = m.get("content", "")
        if isinstance(content, list):
            parts.append("\n".join(b.get("text", "") for b in content if isinstance(b, dict)))
        else:
            parts.append(content or "")
    text = "\n".join(parts)
    wrapped = f"<{_SYSTEM_CLOAK_TAG}>\n{text}\n</{_SYSTEM_CLOAK_TAG}>"
    block: dict = {"type": "text", "text": wrapped}
    cached = len(text) >= _SYSTEM_CACHE_MIN_CHARS
    if cached:
        block["cache_control"] = _SYSTEM_CACHE_CONTROL
    folded = [{"role": "user", "content": [block]}]
    rest = [m for m in messages if m.get("role") != "system"]
    return folded + rest, cached


def _flatten_system_for_openai(messages: list[dict]) -> list[dict]:
    """Collapse the leading system blocks into a single plain system string."""
    system = messages[0]
    blocks = system.get("content", [])
    text = "\n".join(b.get("text", "") for b in blocks if b.get("text"))
    return [{"role": "system", "content": text}] + messages[1:]


def _has_cache_control(messages: list[dict]) -> bool:
    """True when any message content block carries cache_control (FASE 2 cloaked form)."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("cache_control"):
                    return True
    return False


# litellm 1.43.0 strips content-block cache_control before it reaches the proxy, so the
# FASE 2 cached narrator path is routed through the anthropic SDK directly. Adapters below
# reshape the SDK response into the litellm-shaped object _log_call/_cache_tokens expect.
@dataclass
class _SDKUsage:
    prompt_tokens: int
    completion_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


@dataclass
class _SDKMessage:
    content: str


@dataclass
class _SDKChoice:
    message: _SDKMessage


@dataclass
class _SDKResponse:
    choices: list
    usage: _SDKUsage


_anthropic_clients: dict = {}


def _get_anthropic_client(base_url: str, api_key: str):
    """Lazily build and cache an AsyncAnthropic client keyed by (base_url, api_key)."""
    key = (base_url, api_key)
    client = _anthropic_clients.get(key)
    if client is None:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(base_url=base_url, api_key=api_key, max_retries=0)
        _anthropic_clients[key] = client
    return client


@dataclass
class LLMConfig:
    primary_provider: LLMProvider = LLMProvider.DEEPSEEK
    primary_model: str = "deepseek-v4-flash"
    orchestrator_model: str | None = None
    fallback_provider: LLMProvider | None = None
    fallback_model: str | None = None
    temperature: float = 0.85
    max_tokens: int = 2000

    def get_context_window(self) -> int:
        """Return the context window size (tokens) for the orchestrator model."""
        model = self.orchestrator_model or self.primary_model
        model_key = (
            model
            if self.primary_provider == LLMProvider.OPENAI
            else f"{self.primary_provider.value}/{model}"
        )
        return _CONTEXT_WINDOWS.get(model_key, _DEFAULT_CONTEXT_WINDOW)


# When ANTHROPIC_PROXY_URL is set, Anthropic requests route through the
# Claude Max Proxy (uses Pro/Max subscription instead of API rate limits).
# Read from settings (which loads .env) before falling back to the shell env,
# otherwise editing .env alone has no effect — pydantic-settings populates the
# settings object but never writes back into os.environ.
from app.config import settings as _settings

_ANTHROPIC_PROXY_URL = _settings.anthropic_proxy_url or os.environ.get("ANTHROPIC_PROXY_URL", "")
_ANTHROPIC_PROXY_KEY = _settings.anthropic_proxy_key or os.environ.get("ANTHROPIC_PROXY_KEY", "proxy")


class LLMRouter:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_model_string(self, provider: LLMProvider, model: str) -> str:
        if provider == LLMProvider.OPENAI:
            return model
        return f"{provider.value}/{model}"

    def _active_model(self, orchestrator: bool) -> str:
        """Orchestrator calls use the dedicated model when one is configured."""
        if orchestrator and self.config.orchestrator_model:
            return self.config.orchestrator_model
        return self.config.primary_model

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

    def _sampling_kwargs(self, model: str) -> dict:
        """Sampling params for models that accept them; empty for the rest."""
        if _accepts_temperature(model):
            return {"temperature": self.config.temperature}
        return {}

    def _prepare_cached_messages(self, messages: list[dict], call_kwargs: dict) -> list[dict]:
        """Apply the FASE 2 provider transform to cached-form messages.

        Anthropic path: cloak zones into the first user message and set the
        extended-cache-ttl beta header. Other providers: flatten to a system
        string. Plain (non-cached-form) messages pass through untouched.
        """
        if not _is_cached_form(messages):
            return messages
        if self.config.primary_provider == LLMProvider.ANTHROPIC:
            call_kwargs["extra_headers"] = {
                **_CACHE_HEADERS,
                **call_kwargs.get("extra_headers", {}),
            }
            return _cloak_messages_for_anthropic(messages)
        return _flatten_system_for_openai(messages)

    async def _complete_anthropic_sdk(
        self, messages: list[dict], max_tokens: int, model: str,
        api_base: str, extra_headers: dict | None, caller: str,
    ) -> _SDKResponse:
        """Send a cached-form Anthropic request through the anthropic SDK, preserving
        cache_control (which litellm drops). Retries transient failures; returns a
        litellm-shaped adapter so _log_call reads real cache usage."""
        messages, _ = _fold_system_into_user(messages)
        client = _get_anthropic_client(api_base, _ANTHROPIC_PROXY_KEY)
        bare_model = model.split("/")[-1]
        last_exc: Exception | None = None
        total_attempts = len(_PROXY_RETRY_DELAYS) + 1
        for attempt in range(total_attempts):
            try:
                msg = await client.messages.create(
                    model=bare_model,
                    max_tokens=max_tokens,
                    messages=messages,
                    extra_headers=extra_headers or None,
                    **self._sampling_kwargs(bare_model),
                )
                text = "".join(
                    getattr(b, "text", "") for b in msg.content
                    if getattr(b, "type", None) == "text"
                )
                u = msg.usage
                usage = _SDKUsage(
                    prompt_tokens=getattr(u, "input_tokens", 0) or 0,
                    completion_tokens=getattr(u, "output_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                    cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                )
                return _SDKResponse(choices=[_SDKChoice(_SDKMessage(text))], usage=usage)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Anthropic SDK call failed (attempt %d/%d) [%s] err=%s: %s",
                    attempt + 1, total_attempts, caller, type(exc).__name__, exc,
                )
                if attempt < len(_PROXY_RETRY_DELAYS):
                    await asyncio.sleep(_PROXY_RETRY_DELAYS[attempt])
        assert last_exc is not None
        raise last_exc

    async def complete(self, messages: list[dict], **kwargs) -> str:
        caller = _get_caller()
        orchestrator = kwargs.pop("orchestrator", False)
        model = self._build_model_string(
            self.config.primary_provider, self._active_model(orchestrator)
        )
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        reasoning = kwargs.pop("reasoning", True)
        api_base = self._get_api_base(self.config.primary_provider)
        call_kwargs = {**kwargs}
        call_kwargs.update(_reasoning_kwargs(self.config.primary_provider, reasoning))
        if self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages = self._sanitize_messages_for_anthropic(messages)
        messages = self._prepare_cached_messages(messages, call_kwargs)
        if api_base and self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages, folded_cached = _fold_system_into_user(messages)
            if folded_cached:
                call_kwargs["extra_headers"] = {
                    **_CACHE_HEADERS,
                    **call_kwargs.get("extra_headers", {}),
                }
        if api_base:
            call_kwargs["api_base"] = api_base
            call_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
        if (api_base and self.config.primary_provider == LLMProvider.ANTHROPIC
                and _has_cache_control(messages)):
            t0 = time.monotonic()
            resp = await self._complete_anthropic_sdk(
                messages, max_tokens, model, api_base,
                call_kwargs.get("extra_headers"), caller,
            )
            _log_call(caller + "(anthropic-sdk)", messages, max_tokens, resp,
                      time.monotonic() - t0, model=model)
            return resp.choices[0].message.content
        t0 = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                **self._sampling_kwargs(model),
                **call_kwargs,
            )
            _log_call(caller, messages, max_tokens, response, time.monotonic() - t0, model=model)
            return response.choices[0].message.content
        except Exception:
            if self.config.fallback_provider and self.config.fallback_model:
                fallback_model = self._build_model_string(
                    self.config.fallback_provider, self.config.fallback_model
                )
                fb_api_base = self._get_api_base(self.config.fallback_provider)
                fb_kwargs = {**kwargs}
                fb_kwargs.update(_reasoning_kwargs(self.config.fallback_provider, reasoning))
                if fb_api_base:
                    fb_kwargs["api_base"] = fb_api_base
                    fb_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
                response = await litellm.acompletion(
                    model=fallback_model,
                    messages=messages,
                    max_tokens=self.config.max_tokens,
                    **self._sampling_kwargs(fallback_model),
                    **fb_kwargs,
                )
                _log_call(caller, messages, max_tokens, response, time.monotonic() - t0, model=fallback_model)
                return response.choices[0].message.content
            raise

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        caller = _get_caller()
        orchestrator = kwargs.pop("orchestrator", False)
        model = self._build_model_string(
            self.config.primary_provider, self._active_model(orchestrator)
        )
        max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
        reasoning = kwargs.pop("reasoning", True)
        api_base = self._get_api_base(self.config.primary_provider)
        call_kwargs = {**kwargs}
        call_kwargs.update(_reasoning_kwargs(self.config.primary_provider, reasoning))
        if self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages = self._sanitize_messages_for_anthropic(messages)
        messages = self._prepare_cached_messages(messages, call_kwargs)
        if api_base and self.config.primary_provider == LLMProvider.ANTHROPIC:
            messages, folded_cached = _fold_system_into_user(messages)
            if folded_cached:
                call_kwargs["extra_headers"] = {
                    **_CACHE_HEADERS,
                    **call_kwargs.get("extra_headers", {}),
                }
        if api_base:
            call_kwargs["api_base"] = api_base
            call_kwargs["api_key"] = _ANTHROPIC_PROXY_KEY
            # FASE 2: cached-form Anthropic requests go through the anthropic SDK
            # directly. litellm strips content-block cache_control, killing the cache.
            if (self.config.primary_provider == LLMProvider.ANTHROPIC
                    and _has_cache_control(messages)):
                t0 = time.monotonic()
                resp = await self._complete_anthropic_sdk(
                    messages, max_tokens, model, api_base,
                    call_kwargs.get("extra_headers"), caller,
                )
                _log_call(caller + "(anthropic-sdk)", messages, max_tokens, resp,
                          time.monotonic() - t0, model=model)
                content = resp.choices[0].message.content
                if content:
                    yield content
                return
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
                        max_tokens=max_tokens,
                        stream=False,
                        **self._sampling_kwargs(model),
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
            _log_call(caller + "(stream→sync)", messages, max_tokens, response, time.monotonic() - t0, model=model)
            content = response.choices[0].message.content
            if content:
                yield content
            return
        t0 = time.monotonic()
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            **self._sampling_kwargs(model),
            **call_kwargs,
        )
        output_chars = 0
        accumulated = ""
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                output_chars += len(delta)
                accumulated += delta
                yield delta
        # For streaming, estimate tokens from output chars
        system_chars, total_chars = _count_message_chars(messages)
        elapsed = round(time.monotonic() - t0, 2)
        entry = {
            "caller": caller + "(stream)",
            "model": model,
            "input_tokens": total_chars // 4,
            "output_tokens": output_chars // 4,
            "cache_read": 0,
            "cache_creation": 0,
            "max_tokens": max_tokens,
            "elapsed_s": elapsed,
            "msg_count": len(messages),
            "system_chars": system_chars,
        }
        if _TRACE_ENABLED:
            entry["input"] = _trace_sections(messages)
            entry["output"] = accumulated
        _call_log.append(entry)
        logger.warning(
            "🔥 LLM CALL [%s] input≈%d output≈%d max=%d time=%.1fs msgs=%d sys_chars=%d",
            entry["caller"], entry["input_tokens"], entry["output_tokens"],
            max_tokens, entry["elapsed_s"], len(messages), system_chars,
        )
        if not accumulated.strip():
            logger.error(
                "🚨 LLM EMPTY OUTPUT [%s] model=%s max_tokens=%d finish_reason=%s "
                "output_tokens=%d reasoning_tokens=%d — model spent the budget before writing an answer",
                entry["caller"], model, max_tokens, "", entry["output_tokens"], 0,
            )
        _dump_call(
            caller=caller + "(stream)",
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            response_text=accumulated,
            input_tokens=total_chars // 4,
            output_tokens=output_chars // 4,
            elapsed=elapsed,
            streamed=True,
        )
