from __future__ import annotations
from enum import Enum


class TickType(str, Enum):
    MICRO = "MICRO"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    HEAVY = "HEAVY"


# Thresholds in narrative seconds
_THRESHOLDS = [
    (3600, TickType.MICRO),       # < 1 hour
    (86400, TickType.MINOR),      # 1 hour – 1 day
    (604800, TickType.MODERATE),  # 1 day – 1 week
    (2592000, TickType.MAJOR),    # 1 week – 1 month
]

_TICK_PROMPTS = {
    TickType.MINOR: (
        "Briefly describe routine NPC movements or one minor public development. "
        "Keep it to 2-3 sentences of narrative prose."
    ),
    TickType.MODERATE: (
        "Describe one established faction decision or moderate public world shift. "
        "3-4 sentences of narrative prose."
    ),
    TickType.MAJOR: (
        "Describe significant political shifts, important NPC life events, and notable world changes. "
        "4-5 sentences of narrative prose."
    ),
    TickType.HEAVY: (
        "Describe major world transformations: wars begun or ended, alliances forged, deaths of notable figures, "
        "and sweeping changes to the political landscape. 5-6 sentences of narrative prose."
    ),
}

_WORLD_CHANGE_RULES = (
    "Prefer direct, observable changes that follow established schedules, goals, and consequences. "
    "Keep one primary development. A quiet interval may advance routine activity without escalation. "
    "Do not create a new mystery, secret investigation, conspiracy, or hidden threat unless the world "
    "context already makes it active."
)


class WorldReactor:
    def __init__(self, llm):
        self._llm = llm

    def classify_tick(self, narrative_seconds: int) -> TickType:
        for threshold, tick_type in _THRESHOLDS:
            if narrative_seconds < threshold:
                return tick_type
        return TickType.HEAVY

    async def process_tick(
        self,
        campaign_id: str,
        narrative_seconds: int,
        world_context: str,
        language: str = "en",
    ) -> str:
        tick_type = self.classify_tick(narrative_seconds)
        if tick_type == TickType.MICRO:
            return ""

        prompt_instruction = _TICK_PROMPTS[tick_type]
        hours = narrative_seconds // 3600
        time_desc = (
            f"{narrative_seconds // 60} minutes" if narrative_seconds < 3600
            else f"{hours} hours" if hours < 24
            else f"{hours // 24} days"
        )

        lang_hint = ""
        if language and language != "en":
            lang_hint = f" Write your response in {language}."

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a world simulation engine for an AI RPG. {prompt_instruction} "
                    f"{_WORLD_CHANGE_RULES} "
                    "Write only world changes as narrative facts. No player perspective. "
                    f"No dialogue. Present tense.{lang_hint}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"World context:\n{world_context}\n\n"
                    f"Narrative time elapsed: {time_desc}. "
                    "What changes in the world during this time?"
                ),
            },
        ]
        try:
            return await self._llm.complete(messages=messages, max_tokens=512, reasoning=False)
        except Exception:
            return self._fallback_world_change(tick_type, time_desc)

    @staticmethod
    def _fallback_world_change(tick_type: TickType, time_desc: str) -> str:
        if tick_type == TickType.MINOR:
            return f"Over {time_desc}, rumors spread and patrol patterns subtly change across the region."
        if tick_type == TickType.MODERATE:
            return f"Across {time_desc}, factions reposition resources and local loyalties begin to shift."
        if tick_type == TickType.MAJOR:
            return f"During {time_desc}, political pressure reshapes alliances and key leaders adjust their plans."
        return f"After {time_desc}, the balance of power changes dramatically and multiple fronts destabilize."
