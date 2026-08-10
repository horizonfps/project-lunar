from __future__ import annotations

import logging
from dataclasses import dataclass

from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)

_NONE_MARKERS = {"none", "null", "n/a", "skip", "\"none\"", "'none'"}


def _is_none_response(raw: str) -> bool:
    """Check if the LLM decided not to generate anything."""
    return raw.strip().lower() in _NONE_MARKERS


_CONTEXT_RULES = (
    "\n\nCONTEXT RULES — READ CAREFULLY:\n"
    "- The generated content MUST fit naturally into the current scene and narrative moment.\n"
    "- Respect the tone and setting described in the scenario instructions.\n"
    "- Do NOT introduce elements that contradict or overshadow the current scene.\n"
    "- Do NOT reveal major plot secrets or endgame-level threats prematurely.\n"
    "- Do NOT introduce characters or events that belong to a later narrative arc "
    "(e.g., don't introduce academy characters during the family arc, don't introduce "
    "dragons or world-level threats in the early story).\n"
    "- The content should ADD to the current moment, not derail it.\n"
    "- Prefer direct, visible goals and consequences over mysteries, sabotage, "
    "coded clues, secret investigations, or hidden conspiracies.\n"
    "- Keep only one main complication active. Develop or resolve it before adding another.\n"
    "- Ordinary scenes may remain ordinary. Not every detail needs a deeper explanation.\n"
    "- If the current scene is tense/dramatic (combat, confrontation, ceremony), "
    "do NOT interrupt it with unrelated content.\n"
    "\nCRITICAL: If generating something right now would feel forced, unnatural, "
    "or would break the flow of the current scene, respond with ONLY the word: NONE\n"
    "Responding NONE is ALWAYS acceptable and preferred over generating bad content."
)


@dataclass
class GeneratedNPC:
    name: str
    personality: str
    power_level: int
    secret: str
    goal: str
    appearance: str


@dataclass
class RandomEvent:
    title: str
    description: str
    choices: list[str]


@dataclass
class MicroHook:
    """A small narrative detail for the narrator to weave into the next response."""
    description: str


@dataclass(frozen=True)
class AutoPlotRule:
    kind: str
    min_turns: int
    min_narrative_seconds: int
    cooldown_turns: int
    cooldown_narrative_seconds: int
    max_triggers: int = 999


AUTO_PLOT_RULES: dict[str, AutoPlotRule] = {
    # Micro-hooks: small scene details woven into narrator responses.
    "micro_hook": AutoPlotRule(
        kind="micro_hook",
        min_turns=5,
        min_narrative_seconds=30 * 60,
        cooldown_turns=6,
        cooldown_narrative_seconds=2 * 60 * 60,
        max_triggers=8,
    ),
    # Periodic introduction of new social vectors.
    "npc": AutoPlotRule(
        kind="npc",
        min_turns=8,
        min_narrative_seconds=2 * 60 * 60,
        cooldown_turns=10,
        cooldown_narrative_seconds=24 * 60 * 60,
        max_triggers=6,
    ),
    # Macro-level narrative arcs — future story branches.
    "plot_arc": AutoPlotRule(
        kind="plot_arc",
        min_turns=12,
        min_narrative_seconds=24 * 60 * 60,
        cooldown_turns=14,
        cooldown_narrative_seconds=3 * 24 * 60 * 60,
        max_triggers=4,
    ),
}


class PlotGenerator:
    def __init__(self, llm):
        self._llm = llm

    @staticmethod
    def should_trigger_auto(
        rule: AutoPlotRule,
        turns_since_last: int,
        narrative_seconds_since_last: int,
        trigger_count: int,
    ) -> bool:
        if trigger_count >= rule.max_triggers:
            return False

        if trigger_count == 0:
            return (
                turns_since_last >= rule.min_turns
                and narrative_seconds_since_last >= rule.min_narrative_seconds
            )

        return (
            turns_since_last >= rule.cooldown_turns
            and narrative_seconds_since_last >= rule.cooldown_narrative_seconds
        )

    async def generate_npc(
        self,
        world_context: str,
        language: str = "en",
        recent_narrative: str = "",
        existing_npc_names: list[str] | None = None,
        tone_instructions: str = "",
    ) -> GeneratedNPC | None:
        lang_hint = f" Write all text values in {language}." if language and language != "en" else ""
        recent_hint = f"\n\nRecent narrative:\n{recent_narrative}" if recent_narrative else ""
        tone_hint = f"\n\nScenario tone and setting:\n{tone_instructions[:2000]}" if tone_instructions else ""
        dedup_hint = ""
        if existing_npc_names:
            names_str = ", ".join(existing_npc_names[:30])
            dedup_hint = (
                f"\n\nIMPORTANT: These NPCs already exist in the story: [{names_str}]. "
                "Generate a DIFFERENT character with a UNIQUE name. Do NOT reuse or create "
                "variations of existing names."
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a useful supporting NPC for this RPG world. "
                    "The NPC should be relevant to the current scene and recent events. "
                    "The NPC should be someone the player could realistically encounter "
                    "in their current location and situation — a merchant, a guard, a traveler, "
                    "a rival, a servant, etc. NOT a major plot character or world-shaking figure. "
                    "Most supporting NPCs do not need a secret. Use an empty string unless "
                    "the established scene already requires relevant private information. "
                    "Do not use the NPC to begin a new conspiracy or investigation. "
                    "Return ONLY valid JSON (no markdown): "
                    '{"name": str, "personality": str, "power_level": int (1-10), '
                    f'"secret": str, "goal": str, "appearance": str}}.{lang_hint}'
                    f"{_CONTEXT_RULES}"
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}{tone_hint}{recent_hint}{dedup_hint}"},
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=2048, reasoning=False)
        except Exception:
            logger.exception("NPC generation failed")
            return None
        if _is_none_response(raw):
            logger.info("NPC generation skipped — LLM returned NONE (not appropriate for current scene)")
            return None
        data = parse_json_dict(raw)
        if data:
            try:
                power = max(1, min(10, int(data.get("power_level", 5))))
            except (TypeError, ValueError):
                power = 5
            return GeneratedNPC(
                name=data.get("name", "Unknown"),
                personality=data.get("personality", ""),
                power_level=power,
                secret=data.get("secret", ""),
                goal=data.get("goal", ""),
                appearance=data.get("appearance", ""),
            )
        else:
            logger.warning("NPC generation returned unparseable response: %s", raw[:200])
            return None

    async def generate_random_event(
        self,
        location: str,
        world_context: str,
        narrative_time: int,
        language: str = "en",
        recent_narrative: str = "",
        tone_instructions: str = "",
    ) -> RandomEvent | None:
        time_desc = (
            f"{narrative_time // 86400} days"
            if narrative_time >= 86400
            else f"{narrative_time // 3600} hours"
            if narrative_time >= 3600
            else f"{narrative_time // 60} minutes"
        )
        lang_hint = f" Write all text values in {language}." if language and language != "en" else ""
        recent_hint = f"\nRecent narrative:\n{recent_narrative}" if recent_narrative else ""
        tone_hint = f"\nScenario tone and setting:\n{tone_instructions[:2000]}" if tone_instructions else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a contextually appropriate random encounter or event. "
                    "The event should feel natural for the location and moment — "
                    "not forced or out of place. "
                    "Return ONLY valid JSON: "
                    f'{{"title": str, "description": str, "choices": [str, str, str]}}.{lang_hint}'
                    f"{_CONTEXT_RULES}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Location: {location}\n"
                    f"World context: {world_context}\n"
                    f"Time elapsed: {time_desc}"
                    f"{tone_hint}"
                    f"{recent_hint}"
                ),
            },
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=2048, reasoning=False)
        except Exception:
            logger.exception("Random event generation failed")
            return None
        if _is_none_response(raw):
            logger.info("Random event skipped — LLM returned NONE")
            return None
        data = parse_json_dict(raw)
        if data:
            return RandomEvent(
                title=data.get("title", "Unexpected Event"),
                description=data.get("description", ""),
                choices=data.get("choices", []),
            )
        else:
            logger.warning("Random event returned unparseable response: %s", raw[:200])
            return None

    async def generate_plot_arc(
        self,
        world_context: str,
        language: str = "en",
        recent_narrative: str = "",
        tone_instructions: str = "",
    ) -> str | None:
        lang_hint = f" Write in {language}." if language and language != "en" else ""
        recent_hint = f"\n\nRecent story summary:\n{recent_narrative}" if recent_narrative else ""
        tone_hint = f"\n\nScenario tone and setting:\n{tone_instructions[:2000]}" if tone_instructions else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a story architect for an RPG campaign. Generate one direct, visible development "
                    "that can unfold over multiple sessions. "
                    "This is NOT a scene action or something happening right now. "
                    "Prefer open goals and conflicts such as a tournament, a training milestone, "
                    "a public rivalry, a journey, a relationship change, or a visible political move. "
                    "Use mystery, sabotage, betrayal, or a hidden conspiracy only when one is already "
                    "an established unresolved thread in the supplied context. "
                    "Write 2-3 sentences describing WHAT will happen in the future, "
                    "not what is happening now. Keep the development easy to understand and act on. "
                    f"No lists or headers.{lang_hint}"
                    f"{_CONTEXT_RULES}"
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}{tone_hint}{recent_hint}"},
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=2048, reasoning=False)
        except Exception:
            logger.exception("Plot arc generation failed")
            return None
        if _is_none_response(raw):
            logger.info("Plot arc skipped — LLM returned NONE")
            return None
        return raw

    async def generate_micro_hook(
        self,
        world_context: str,
        recent_narrative: str,
        language: str = "en",
        tone_instructions: str = "",
    ) -> MicroHook | None:
        """Generate a small narrative detail for the narrator to weave into the next response.

        Unlike plot arcs, micro-hooks are concrete scene-level details that add
        texture, opportunity, or a visible complication without opening another plot.
        """
        lang_hint = f" Write in {language}." if language and language != "en" else ""
        tone_hint = f"\nScenario tone and setting:\n{tone_instructions[:2000]}" if tone_instructions else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate one concrete narrative detail that the narrator "
                    "should weave into the next response. This is NOT a plot arc or "
                    "a separate event. It must not create a new mystery, conspiracy, "
                    "investigation, hidden presence, secret mechanism, or unexplained clue. "
                    "Useful examples include a mundane interruption, a public announcement, "
                    "a visible training opportunity, a direct social reaction, or a change "
                    "in weather that affects the current action. "
                    "Write ONE sentence describing the detail. Be specific to the "
                    "current scene. If the detail would need a hidden explanation or a second "
                    f"plot thread, return NONE.{lang_hint}"
                    f"{_CONTEXT_RULES}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"World context:\n{world_context}"
                    f"{tone_hint}\n\n"
                    f"Current scene:\n{recent_narrative}"
                ),
            },
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=2048, reasoning=False)
        except Exception:
            logger.exception("Micro-hook generation failed")
            return None
        if _is_none_response(raw):
            logger.info("Micro-hook skipped — LLM returned NONE")
            return None
        stripped = raw.strip()
        if stripped:
            return MicroHook(description=stripped)
        return None
