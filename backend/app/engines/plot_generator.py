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
    # Macro-level narrative arcs — future story branches.
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
        recent_hint = f"\n\nRecent narrative:\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a compelling NPC for this RPG world. "
                    "The NPC should be relevant to the world and could appear in future scenes. "
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
        recent_hint = f"\nRecent narrative:\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a contextually appropriate random encounter or event. "
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
        recent_hint = f"\n\nRecent story summary:\n{recent_narrative}" if recent_narrative else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a story architect for an RPG campaign. Generate a MACRO-LEVEL "
                    "plot arc — a future story branch that will unfold over multiple sessions. "
                    "This is NOT a scene action or something happening right now. "
                    "It is a high-level narrative hook like:\n"
                    "- A villain making moves behind the scenes\n"
                    "- An ally facing a personal crisis\n"
                    "- A political shift in the world\n"
                    "- A new threat emerging far away\n"
                    "- A betrayal being planned\n"
                    "Write 2-3 sentences describing WHAT will happen in the future, "
                    "not what is happening now. Think of it as a TV show's next-episode teaser. "
                    f"No lists or headers.{lang_hint}"
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

    async def generate_micro_hook(self, world_context: str, recent_narrative: str, language: str = "en") -> MicroHook:
        """Generate a small narrative detail for the narrator to weave into the next response.

        Unlike plot arcs, micro-hooks are scene-level details: a mysterious object,
        an NPC behaving oddly, an environmental clue, a sensory detail that hints
        at something deeper. The narrator integrates these naturally into its text.
        """
        lang_hint = f" Write in {language}." if language and language != "en" else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a small, intriguing narrative detail that the narrator "
                    "should weave into the next response. This is NOT a plot arc or "
                    "a separate event — it is a detail the narrator will incorporate "
                    "naturally into the prose. Examples:\n"
                    "- A strange object is found during the current scene\n"
                    "- An NPC reacts oddly to something\n"
                    "- The environment shows an unusual sign\n"
                    "- A sensory detail hints at a hidden presence\n"
                    "- A character notices something no one else does\n"
                    "Write ONE sentence describing the detail. Be specific to the "
                    f"current scene.{lang_hint}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"World context:\n{world_context}\n\n"
                    f"Current scene:\n{recent_narrative}"
                ),
            },
        ]
        try:
            raw = await self._llm.complete(messages=messages)
            return MicroHook(description=raw.strip())
        except Exception:
            return MicroHook(description="")
