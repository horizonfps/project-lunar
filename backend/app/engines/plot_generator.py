from __future__ import annotations
from dataclasses import dataclass

from app.utils.json_parsing import parse_json_dict


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


@dataclass(frozen=True)
class AutoPlotRule:
    kind: str
    min_turns: int
    min_narrative_seconds: int
    cooldown_turns: int
    cooldown_narrative_seconds: int
    max_triggers: int = 999


AUTO_PLOT_RULES: dict[str, AutoPlotRule] = {
    # Frequent micro-hook to keep sessions lively.
    "event": AutoPlotRule(
        kind="event",
        min_turns=3,
        min_narrative_seconds=15 * 60,
        cooldown_turns=4,
        cooldown_narrative_seconds=20 * 60,
        max_triggers=12,
    ),
    # Periodic introduction of new social vectors.
    "npc": AutoPlotRule(
        kind="npc",
        min_turns=5,
        min_narrative_seconds=30 * 60,
        cooldown_turns=6,
        cooldown_narrative_seconds=45 * 60,
        max_triggers=8,
    ),
    # Less frequent, macro-level narrative branch.
    "plot_arc": AutoPlotRule(
        kind="plot_arc",
        min_turns=8,
        min_narrative_seconds=2 * 60 * 60,
        cooldown_turns=9,
        cooldown_narrative_seconds=3 * 60 * 60,
        max_triggers=6,
    ),
}


_FALLBACK_NPC = GeneratedNPC(
    name="Mysterious Stranger",
    personality="Enigmatic",
    power_level=5,
    secret="Unknown",
    goal="Unknown",
    appearance="Cloaked figure",
)


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

    async def generate_npc(self, world_context: str, language: str = "en", recent_narrative: str = "") -> GeneratedNPC:
        lang_hint = f" Write all text values in {language}." if language and language != "en" else ""
        recent_hint = f"\n\nRecent narrative (the NPC must fit naturally into this scene):\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a compelling NPC for this RPG world. "
                    "The NPC must be contextually relevant to the current scene and situation. "
                    "Return ONLY valid JSON (no markdown): "
                    '{"name": str, "personality": str, "power_level": int (1-10), '
                    f'"secret": str, "goal": str, "appearance": str}}.{lang_hint}'
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}{recent_hint}"},
        ]
        try:
            raw = await self._llm.complete(messages=messages)
        except Exception:
            return _FALLBACK_NPC
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
            return _FALLBACK_NPC

    async def generate_random_event(
        self,
        location: str,
        world_context: str,
        narrative_time: int,
        language: str = "en",
        recent_narrative: str = "",
    ) -> RandomEvent:
        time_desc = (
            f"{narrative_time // 86400} days"
            if narrative_time >= 86400
            else f"{narrative_time // 3600} hours"
            if narrative_time >= 3600
            else f"{narrative_time // 60} minutes"
        )
        lang_hint = f" Write all text values in {language}." if language and language != "en" else ""
        recent_hint = f"\nRecent narrative (the event must connect to this scene):\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a contextually appropriate random encounter or event. "
                    "The event must make sense given what is currently happening in the story. "
                    "Return ONLY valid JSON: "
                    f'{{"title": str, "description": str, "choices": [str, str, str]}}.{lang_hint}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Location: {location}\n"
                    f"World context: {world_context}\n"
                    f"Time elapsed: {time_desc}"
                    f"{recent_hint}"
                ),
            },
        ]
        try:
            raw = await self._llm.complete(messages=messages)
        except Exception:
            return RandomEvent(
                title="Unexpected Event",
                description="Something unusual happens.",
                choices=["Investigate", "Ignore", "Leave"],
            )
        data = parse_json_dict(raw)
        if data:
            return RandomEvent(
                title=data.get("title", "Unexpected Event"),
                description=data.get("description", ""),
                choices=data.get("choices", []),
            )
        else:
            return RandomEvent(
                title="Unexpected Event",
                description="Something unusual happens.",
                choices=["Investigate", "Ignore", "Leave"],
            )

    async def generate_plot_arc(self, world_context: str, language: str = "en", recent_narrative: str = "") -> str:
        lang_hint = f" Write in {language}." if language and language != "en" else ""
        recent_hint = f"\n\nRecent narrative (the plot hook must connect naturally to this scene):\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a compelling plot hook for a new quest or story branch. "
                    "The hook must be a FUTURE seed — something that could naturally emerge "
                    "from the current scene, not something that contradicts or interrupts it. "
                    "It should feel like a foreshadowing or a consequence of recent events. "
                    f"Write 2-3 sentences of narrative prose. No lists or headers.{lang_hint}"
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}{recent_hint}"},
        ]
        try:
            return await self._llm.complete(messages=messages)
        except Exception:
            return (
                "A sealed archive contains proof that a trusted ally serves two masters. "
                "If exposed, old alliances may collapse before the next moonrise."
            )
