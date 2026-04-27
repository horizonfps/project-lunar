"""Generates a one-of-a-kind cold-open for a campaign.

Used when ``scenario.opening_mode == 'ai'``. The narrator LLM is given the
scenario's full tone and lore, plus the player's setup answers (formatted
as ``CHARACTER SETUP`` lines that mirror the in-game system prompt block).

This module deliberately does NOT truncate the inputs — Project Lunar targets
Claude's 1M-context window; the dynamic budget refactor will land later but
for now it is preferable to send the full content rather than hide details
from the model.
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.engines.llm_router import LLMRouter

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You write the cold-open of an interactive narrative RPG.

Constraints:
- Second person ("You ...").
- 180-360 words, 4-8 short paragraphs.
- Honor the SCENARIO TONE rules and the world LORE.
- Establish setting, sensory detail, and one immediate dramatic hook.
- Reference the player's CHARACTER SETUP organically — never list it as
  a stat block.
- End on a question, beat, or speaker-tag that invites the player's first
  action; do not narrate the player's response.
- No headings, no markdown beyond paragraph breaks.
"""


def format_setup_lines(
    answers: dict,
    questions: Iterable[dict] | None = None,
) -> list[str]:
    """Render setup answers as ``- var_name: value`` (description) lines.

    Optional ``questions`` is consulted only to preserve the wizard's order
    when iterating answer values; if it's omitted, dict insertion order is
    used. Empty values are skipped.
    """
    lines: list[str] = []
    if not answers:
        return lines

    if questions:
        ordered_keys = [q.get("var_name") for q in questions if q.get("var_name")]
        seen = set(ordered_keys)
        ordered_keys += [k for k in answers.keys() if k not in seen]
    else:
        ordered_keys = list(answers.keys())

    for key in ordered_keys:
        ans = answers.get(key)
        if not isinstance(ans, dict):
            continue
        value = (ans.get("value") or "").strip()
        if not value:
            continue
        var_name = ans.get("var_name") or key
        description = (ans.get("description") or "").strip()
        line = f"- {var_name}: {value}"
        if description:
            line += f"\n  ({description})"
        lines.append(line)
    return lines


def synthesize_sample_answers(questions: Iterable[dict]) -> dict:
    """Build placeholder answers from a scenario's setup questions.

    Used by the author-side preview button when the author hasn't supplied
    sample answers manually. For ``choice`` questions we pick the first option;
    for ``text`` questions we use the var name as a stand-in.
    """
    sample: dict = {}
    for q in questions or []:
        var_name = q.get("var_name")
        if not var_name:
            continue
        qtype = q.get("type", "text")
        if qtype == "choice" and q.get("options"):
            opt = q["options"][0]
            label = opt.get("label", var_name)
            description = opt.get("description", "")
            sample[var_name] = {
                "var_name": var_name,
                "type": "choice",
                "value": label,
                "description": description,
            }
        else:
            sample[var_name] = {
                "var_name": var_name,
                "type": "text",
                "value": var_name.replace("_", " ").title(),
                "description": "",
            }
    return sample


async def generate_opening(
    *,
    language: str,
    tone: str,
    lore: str,
    character_setup_lines: list[str],
    director_note: str = "",
    router: LLMRouter,
    max_tokens: int = 900,
) -> str:
    """Ask the narrator LLM to write a fresh opening.

    Returns the raw text. Caller decides whether to persist it.
    """
    setup_block = "\n".join(character_setup_lines) if character_setup_lines else "(none provided)"
    parts = [
        f"LANGUAGE: write the entire opening in {language}.",
        f"\nSCENARIO TONE:\n{tone or '(unspecified)'}",
        f"\nWORLD LORE:\n{lore or '(unspecified)'}",
        f"\nCHARACTER SETUP:\n{setup_block}",
    ]
    if director_note.strip():
        parts.append(f"\nDIRECTOR'S NOTE:\n{director_note.strip()}")
    parts.append("\nWrite the cold-open now.")
    user = "\n".join(parts)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    text = await router.complete(messages, max_tokens=max_tokens)
    return (text or "").strip()
