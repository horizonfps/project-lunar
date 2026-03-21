from __future__ import annotations
import logging
import re
from enum import Enum
from typing import AsyncIterator

from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English, ~3 for CJK-heavy text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


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

    def _build_narrator_rules(self, max_tokens: int) -> str:
        """Build the static narrator rules block (same for all actions in a scenario)."""
        length_instruction = self._length_instruction(max_tokens)
        return (
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

    def build_system_prompt(
        self,
        tone_instructions: str,
        memory_context: str,
        language: str,
        inventory_context: str = "",
        max_tokens: int = 2000,
        narrator_hints: str = "",
        graph_context: str = "",
        npc_context: str = "",
        journal_context: str = "",
        story_cards_context: str = "",
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
        if npc_context:
            sections.append(f"\n{npc_context}")
        if journal_context:
            sections.append(f"\n{journal_context}")
        if narrator_hints:
            sections.append(narrator_hints)
        if graph_context:
            sections.append(f"\nWORLD RELATIONSHIPS (who knows who, connections between entities):\n{graph_context}")
        if story_cards_context:
            sections.append(f"\n{story_cards_context}")

        sections.append(self._build_narrator_rules(max_tokens))
        return "\n".join(sections)

    def build_system_prompt_parts(
        self,
        tone_instructions: str,
        memory_context: str,
        language: str,
        inventory_context: str = "",
        max_tokens: int = 2000,
        narrator_hints: str = "",
        graph_context: str = "",
        npc_context: str = "",
        journal_context: str = "",
        story_cards_context: str = "",
    ) -> tuple[str, str]:
        """Build system prompt split into (static, dynamic) parts for prompt caching.

        Static part: role + language + tone + narrator rules (fixed per scenario).
        Dynamic part: memory, inventory, NPCs, journal, hints, graph, story cards (changes per action).
        No artificial character limit — the context budget is managed at the
        session level based on the provider's actual context window.
        """
        lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
            language,
            f"Respond in the language: {language}.",
        )

        # Static: same for every action in this scenario
        static_sections = [
            f"You are an AI narrator for an interactive RPG story. {lang_instruction}",
        ]
        if tone_instructions:
            static_sections.append(f"\nTONE AND STYLE:\n{tone_instructions}")
        static_sections.append(self._build_narrator_rules(max_tokens))
        static_part = "\n".join(static_sections)

        # Dynamic: changes every action
        dynamic_sections: list[str] = []
        if memory_context:
            dynamic_sections.append(f"\nWORLD MEMORY:\n{memory_context}")
        if inventory_context:
            dynamic_sections.append(f"\nPLAYER INVENTORY:\n{inventory_context}")
        if npc_context:
            dynamic_sections.append(f"\n{npc_context}")
        if journal_context:
            dynamic_sections.append(f"\n{journal_context}")
        if narrator_hints:
            dynamic_sections.append(narrator_hints)
        if graph_context:
            dynamic_sections.append(f"\nWORLD RELATIONSHIPS (who knows who, connections between entities):\n{graph_context}")
        if story_cards_context:
            dynamic_sections.append(f"\n{story_cards_context}")

        dynamic_part = "\n".join(dynamic_sections)
        return static_part, dynamic_part

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

    @staticmethod
    def _dynamic_history_slice(history: list[dict], context_window: int, system_tokens: int) -> list[dict]:
        """Return as many recent history messages as fit within the context budget.

        Budget allocation:
        - system_tokens: already consumed by the system prompt
        - output reserve: 2500 tokens (narrative + JSON overhead)
        - remaining budget goes to history, newest messages first
        """
        output_reserve = 2500
        budget = context_window - system_tokens - output_reserve
        if budget <= 0:
            return history[-4:]  # absolute minimum: keep last 2 exchanges

        selected: list[dict] = []
        used = 0
        for msg in reversed(history):
            msg_tokens = estimate_tokens(msg.get("content", ""))
            if used + msg_tokens > budget:
                break
            selected.append(msg)
            used += msg_tokens
        selected.reverse()
        # Always keep at least 4 messages (2 exchanges) for coherence
        if len(selected) < 4 and len(history) >= 4:
            selected = history[-4:]
        return selected

    async def stream_narrative(
        self,
        player_input: str,
        system_prompt: str,
        history: list[dict],
        context_window: int = 64_000,
    ) -> AsyncIterator[str]:
        system_tokens = estimate_tokens(system_prompt)
        history_slice = self._dynamic_history_slice(history, context_window, system_tokens)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_slice)
        messages.append({"role": "user", "content": player_input})
        try:
            async for chunk in self._llm.stream(messages=messages):
                yield chunk
        except Exception:
            yield self._fallback_narrative(player_input)

    _SINGLE_CALL_FORMAT = (
        "\n\n=== RESPONSE FORMAT ===\n"
        "You MUST return ONLY valid JSON (no markdown fences) with this exact schema:\n"
        "{\n"
        '  "mode": "NARRATIVE|COMBAT|META",\n'
        '  "narrative_time_seconds": <int, realistic story time this action takes>,\n'
        '  "ambush": <bool, true only if NPC attacks player by surprise>,\n'
        '  "narrative_text": "<your full narrative prose response>",\n'
        '  "npc_thoughts": [{"name": "<full NPC name>", "thoughts": {"feeling": "...", "goal": "...", "opinion_of_player": "...", "secret_plan": "..."}}],\n'
        '  "entities": [{"name": "<full name>", "type": "NPC|LOCATION|FACTION|ITEM|EVENT", "attributes": {}}],\n'
        '  "relationships": [{"source": "<full name>", "target": "<full name>", "rel_type": "KNOWS|MET|ALLIED_WITH|GUARDS|LOCATED_IN|etc"}],\n'
        '  "world_changes": "<brief description of background world changes, or empty string if none>"\n'
        "}\n\n"
        "IMPORTANT RULES FOR THIS FORMAT:\n"
        "- narrative_text: Write your full immersive narrative here. All narrator rules still apply.\n"
        "- mode: COMBAT if action is a fight, META if player speaks out-of-character, NARRATIVE otherwise.\n"
        "- npc_thoughts: Only include NPCs that APPEAR or are MENTIONED in this scene.\n"
        "- entities/relationships: Extract named entities from your narrative. Use FULL canonical names.\n"
        "- world_changes: Only if significant time passes or major events affect the wider world. Empty string otherwise.\n"
        "- The narrative_text must be complete, immersive prose — not a summary."
    )

    async def complete_single_call(
        self,
        player_input: str,
        static_prompt: str,
        dynamic_prompt: str,
        history: list[dict],
        canonical_names: list[str] | None = None,
        max_tokens: int = 2000,
        context_window: int = 200_000,
    ) -> dict:
        """Single LLM call that returns narrative + all side-effect data as JSON.

        Uses Anthropic prompt caching: the static part (role + tone + rules + format)
        is marked with cache_control so it's cached across actions in the same scenario.
        The dynamic part (memory, NPCs, etc.) changes every action and is not cached.
        History window is dynamically sized based on the provider's context window.
        """
        names_hint = ""
        if canonical_names:
            names_str = ", ".join(canonical_names[:40])
            names_hint = (
                f"\nKNOWN ENTITIES (use these exact names for entity extraction): [{names_str}]"
            )

        # Static part: role + tone + narrator rules + JSON format (cached per scenario)
        cached_text = static_prompt + self._SINGLE_CALL_FORMAT

        # Dynamic part: memory + NPCs + hints + entity names (changes every action)
        dynamic_text = dynamic_prompt + names_hint

        # Dynamic history window based on context budget
        system_tokens = estimate_tokens(cached_text) + estimate_tokens(dynamic_text)
        history_slice = self._dynamic_history_slice(history, context_window, system_tokens)

        # Build messages with cache_control on the static block
        messages = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": cached_text,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": dynamic_text,
                    },
                ],
            },
        ]
        messages.extend(history_slice)
        messages.append({"role": "user", "content": player_input})

        try:
            # User's narrative budget + 1500 tokens overhead for JSON metadata
            api_max_tokens = max_tokens + 1500
            raw = await self._llm.complete(messages=messages, max_tokens=api_max_tokens)
            parsed = parse_json_dict(raw)
            if parsed and parsed.get("narrative_text"):
                return parsed
            # JSON parsed but no narrative_text — log for debugging
            if parsed:
                logger.warning("Single-call: JSON parsed but missing narrative_text. Keys: %s", list(parsed.keys()))
            else:
                logger.warning(
                    "Single-call: Failed to parse JSON from LLM response (length=%d). First 500 chars: %s",
                    len(raw) if raw else 0,
                    (raw or "")[:500],
                )
        except Exception:
            logger.warning("Single-call narrative failed, using fallback", exc_info=True)

        # Fallback: return minimal structure with fallback narrative
        return {
            "mode": "NARRATIVE",
            "narrative_time_seconds": 60,
            "ambush": False,
            "narrative_text": self._fallback_narrative(player_input),
            "npc_thoughts": [],
            "entities": [],
            "relationships": [],
            "world_changes": "",
        }

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
