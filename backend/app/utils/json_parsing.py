from __future__ import annotations

import json
import re
from typing import Any

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def parse_json_payload(raw: Any) -> dict | list | None:
    """
    Parse JSON payloads from LLM text output.

    Accepts plain JSON, fenced markdown JSON, and JSON wrapped with extra text.
    Returns None when no valid JSON object/array can be extracted.
    """
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    for candidate in _candidate_json_strings(text):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    return None


def parse_json_dict(raw: Any) -> dict | None:
    parsed = parse_json_payload(raw)
    return parsed if isinstance(parsed, dict) else None


def parse_json_list(raw: Any) -> list | None:
    parsed = parse_json_payload(raw)
    return parsed if isinstance(parsed, list) else None


def _candidate_json_strings(text: str) -> list[str]:
    candidates: list[str] = [text]

    code_fence_match = _CODE_FENCE_RE.search(text)
    if code_fence_match:
        candidates.append(code_fence_match.group(1).strip())

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start != -1 and object_end != -1 and object_end > object_start:
        candidates.append(text[object_start:object_end + 1].strip())

    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start != -1 and array_end != -1 and array_end > array_start:
        candidates.append(text[array_start:array_end + 1].strip())

    # Preserve order while removing duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique

