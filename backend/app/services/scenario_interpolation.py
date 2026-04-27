"""Variable interpolation for scenario content (opening, tone, lore).

Mirrors the rules used by the frontend SetupWizard so authors learn one syntax:

  - ``{var_name}``     — replaced by the player's ``setup_answers[var_name].value``
                         (or the answer itself if it's a plain string).
  - ``{{`` / ``}}``    — literal ``{`` / ``}``.
  - ``\\{var}``        — literal ``{var}`` (skips substitution; the leading
                         backslash is removed).  Lets authors write code blocks
                         containing brace-shaped placeholders.
  - missing variable   — token is left literal so authors can spot typos.

Replacement is single-pass: substituted values are not re-interpolated,
which keeps the function safe against recursive answer values.
"""
from __future__ import annotations

import logging
import re
from typing import Any

_VAR_RE = re.compile(r"(\\?)\{([a-z_][a-z0-9_]*)\}")
_logger = logging.getLogger(__name__)

# Sentinels for the {{ / }} escape pre-pass. Using control characters guarantees
# they cannot collide with author-written content.
_OPEN_SENTINEL = "\x00LBR\x00"
_CLOSE_SENTINEL = "\x00RBR\x00"

# Tracks (context, var_name) pairs we've already warned about so a single
# template doesn't spam the log on every render.
_warned: set[tuple[str, str]] = set()


def _coerce_value(answer: Any) -> str | None:
    """Pull a usable string out of whatever the answer dict carries."""
    if answer is None:
        return None
    if isinstance(answer, dict):
        value = answer.get("value")
        if value is None:
            return None
        return str(value).strip() or None
    if isinstance(answer, (int, float, bool)):
        return str(answer)
    text = str(answer).strip()
    return text or None


def interpolate(template: str, answers: dict | None, *, context: str = "") -> str:
    """Substitute ``{var_name}`` tokens with values from ``setup_answers``.

    See module docstring for the full set of rules.
    """
    if not template:
        return ""
    answers = answers or {}

    # Step 1: protect literal {{ / }} from the variable regex.
    work = template.replace("{{", _OPEN_SENTINEL).replace("}}", _CLOSE_SENTINEL)

    missing: set[str] = set()

    def _resolve(match: re.Match) -> str:
        backslash, key = match.group(1), match.group(2)
        if backslash:
            # \{var} → keep {var} literal, drop the backslash.
            return match.group(0)[1:]
        value = _coerce_value(answers.get(key))
        if value is None:
            missing.add(key)
            return match.group(0)
        return value

    out = _VAR_RE.sub(_resolve, work)
    out = out.replace(_OPEN_SENTINEL, "{").replace(_CLOSE_SENTINEL, "}")

    if missing and context:
        unseen = sorted(k for k in missing if (context, k) not in _warned)
        if unseen:
            for k in unseen:
                _warned.add((context, k))
            _logger.warning(
                "Unresolved interpolation tokens in %s: %s",
                context, unseen,
            )
    return out


def reset_warning_cache() -> None:
    """Test helper — clear the per-process dedup cache."""
    _warned.clear()
