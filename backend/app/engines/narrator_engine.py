from __future__ import annotations
import re
from enum import Enum
from typing import AsyncIterator

from app.utils.json_parsing import parse_json_dict


class NarrativeMode(str, Enum):
    NARRATIVE = "NARRATIVE"
    COMBAT = "COMBAT"
    META = "META"


_DEFAULT_META = {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 60}

_LANGUAGE_INSTRUCTIONS = {
    "en": "Respond in English.",
    "pt-br": "Responda em português brasileiro (pt-br).",
}


class NarratorEngine:
    def __init__(self, llm):
        self._llm = llm

    async def detect_mode(self, player_input: str) -> tuple[NarrativeMode, dict]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the player's action and return ONLY JSON: "
                    '{"mode": "NARRATIVE|COMBAT|META", "ambush": bool, "narrative_time_seconds": int}. '
                    "COMBAT: action initiates or continues a fight. "
                    "META: player speaks to the AI narrator directly (out of character). "
                    "NARRATIVE: everything else (exploration, dialogue, travel, etc.). "
                    "ambush: true ONLY if an NPC attacks the player by surprise (not player-initiated). "
                    "narrative_time_seconds: realistic story time this action takes in seconds."
                ),
            },
            {"role": "user", "content": player_input},
        ]
        try:
            raw = await self._llm.complete(messages=messages)
        except Exception:
            return self._heuristic_detect_mode(player_input)

        data = parse_json_dict(raw)
        if not data:
            return self._heuristic_detect_mode(player_input)

        mode_raw = str(data.get("mode", "NARRATIVE")).upper()
        try:
            mode = NarrativeMode(mode_raw)
        except ValueError:
            mode = NarrativeMode.NARRATIVE

        try:
            seconds = int(data.get("narrative_time_seconds", 60))
        except (TypeError, ValueError):
            seconds = 60

        return mode, {
            "mode": mode.value,
            "ambush": bool(data.get("ambush", False)),
            "narrative_time_seconds": seconds,
        }

    @staticmethod
    def _length_instruction(max_tokens: int) -> str:
        """Return a length constraint instruction scaled to the token budget."""
        if max_tokens <= 512:
            return (
                "LENGTH CONSTRAINT: Keep your response very short — 1-2 paragraphs maximum. "
                "Be concise but complete. Always end at a natural stopping point."
            )
        if max_tokens <= 1000:
            return (
                "LENGTH CONSTRAINT: Keep your response short — 2-4 paragraphs maximum. "
                "Focus on the most important narrative beats. Always end at a natural stopping point."
            )
        if max_tokens <= 1500:
            return (
                "LENGTH CONSTRAINT: Keep your response moderate — 4-6 paragraphs maximum. "
                "Always end at a natural stopping point with a clear prompt for the player."
            )
        return ""

    def build_system_prompt(
        self,
        tone_instructions: str,
        memory_context: str,
        language: str,
        inventory_context: str = "",
        max_tokens: int = 2000,
        narrator_hints: str = "",
        graph_context: str = "",
    ) -> str:
        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language,
            f"Respond in the language: {language}.",
        )
        sections = [
            f"You are an AI narrator for an interactive RPG story. {lang_instruction}",
        ]
        if tone_instructions:
            sections.append(f"\nTONE AND STYLE:\n{tone_instructions}")
        if memory_context:
            sections.append(f"\nWORLD MEMORY:\n{memory_context}")
        if inventory_context:
            sections.append(f"\nPLAYER INVENTORY:\n{inventory_context}")
        if narrator_hints:
            sections.append(narrator_hints)
        if graph_context:
            sections.append(f"\nWORLD RELATIONSHIPS (who knows who, connections between entities):\n{graph_context}")

        length_instruction = self._length_instruction(max_tokens)

        sections.append(
            "\nNARRATOR RULES:\n"
            "- Write immersive, evocative prose. Never break character.\n"
            "- React meaningfully to player choices. Consequences are real.\n"
            "- The world is alive — NPCs have their own agendas and memories.\n"
            "- ALWAYS use FULL character names (e.g. 'Megumi Fushiguro' not 'Megumi', 'Satoru Gojo' not 'Gojo'). You may use short names in dialogue spoken by characters, but the narration itself must use full names.\n"
            "- Stay consistent with the established tone.\n"
            "- Do NOT summarize. Narrate in present tense.\n"
            "- End each response at a natural pause, not mid-action.\n"
            "- ALWAYS finish your response with a complete sentence. Never stop mid-word or mid-sentence.\n"
            + (f"- {length_instruction}\n" if length_instruction else "")
            + "- When the player ACQUIRES an item, emit: [ITEM_ADD:item_name|category|source_description]\n"
            "- When an item is CONSUMED or EXPENDED, emit: [ITEM_USE:item_name]\n"
            "- When an item is LOST, STOLEN, or DESTROYED, emit: [ITEM_LOSE:item_name]\n"
            "- Categories: weapon, armor, consumable, quest, tool, misc\n"
            "- If the player tries to use an item NOT in their inventory, reject the action narratively.\n"
            "- Place item tags at the end of the relevant sentence, inline with the narrative."
        )
        return "\n".join(sections)

    def build_meta_prompt(
        self,
        language: str,
        inventory_context: str = "",
        journal_context: str = "",
        npc_context: str = "",
    ) -> str:
        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language,
            f"Respond in the language: {language}.",
        )
        sections = [
            f"You are a Game Master assistant for this RPG campaign. {lang_instruction}",
            "\nMETA MODE RULES:",
            "- Respond OUT-OF-CHARACTER. You are a helpful game master, not a narrator.",
            "- Be factual and direct. No narrative prose, no 'you feel', no scene-setting.",
            "- Reference action numbers and locations when citing events.",
            "- Use bullet points and structured formatting.",
            "- Answer questions about game state using the structured data below.",
        ]
        if inventory_context:
            sections.append(f"\n{inventory_context}")
        if journal_context:
            sections.append(f"\nJOURNAL (recent entries):\n{journal_context}")
        if npc_context:
            sections.append(f"\nACTIVE NPCs:\n{npc_context}")
        return "\n".join(sections)

    async def stream_narrative(
        self,
        player_input: str,
        system_prompt: str,
        history: list[dict],
    ) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": player_input})
        try:
            async for chunk in self._llm.stream(messages=messages):
                yield chunk
        except Exception:
            yield self._fallback_narrative(player_input)

    @staticmethod
    def _heuristic_detect_mode(player_input: str) -> tuple[NarrativeMode, dict]:
        text = player_input.lower()

        combat_markers = (
            "attack", "strike", "slash", "parry", "fight", "combat", "duel",
            "shoot", "stab", "counter", "ambush", "battle",
        )
        meta_markers = ("ooc", "meta", "as ai", "narrator", "system")

        mode = NarrativeMode.NARRATIVE
        if any(marker in text for marker in combat_markers):
            mode = NarrativeMode.COMBAT
        elif any(marker in text for marker in meta_markers):
            mode = NarrativeMode.META

        seconds = NarratorEngine._extract_narrative_seconds(text)
        return mode, {
            "mode": mode.value,
            "ambush": False,
            "narrative_time_seconds": seconds,
        }

    @staticmethod
    def _extract_narrative_seconds(text: str) -> int:
        patterns = [
            (r"(\\d+)\\s*(day|days|dia|dias)", 86400),
            (r"(\\d+)\\s*(hour|hours|hora|horas)", 3600),
            (r"(\\d+)\\s*(minute|minutes|minuto|minutos)", 60),
            (r"(\\d+)\\s*(week|weeks|semana|semanas)", 604800),
        ]
        for pattern, multiplier in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    value = int(match.group(1))
                    return max(60, value * multiplier)
                except ValueError:
                    continue
        return 60

    @staticmethod
    def _fallback_narrative(player_input: str) -> str:
        return (
            "The world shifts in response to your action. "
            f"You proceed with intent: {player_input} "
            "Tension rises as the consequences begin to unfold."
        )
