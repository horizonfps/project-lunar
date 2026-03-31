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

    async def detect_mode(self, player_input: str, story_context: str = "") -> tuple[NarrativeMode, dict]:
        context_hint = ""
        if story_context:
            context_hint = f" Recent story context: {story_context}"
        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the player's action and return ONLY JSON: "
                    '{"mode": "NARRATIVE|COMBAT|META", "ambush": bool, "narrative_time_seconds": int, '
                    '"opponent_name": str, "opponent_power": int}. '
                    "COMBAT: action initiates or continues a fight. "
                    "META: player speaks to the AI narrator directly (out of character). "
                    "NARRATIVE: everything else (exploration, dialogue, travel, etc.). "
                    "ambush: true ONLY if an NPC attacks the player by surprise (not player-initiated). "
                    "narrative_time_seconds: realistic story time this action takes in seconds. "
                    "opponent_name: if COMBAT, the name or description of the opponent being fought (e.g. 'Kael Noir', 'four-legged creature', 'bandit'). Empty string if not COMBAT. "
                    "opponent_power: if COMBAT, estimate the opponent's power level 1-10. "
                    "If a WORLD POWER SCALE is provided in the context, use those NPCs as anchors "
                    "to calibrate the opponent relative to the world. "
                    "Use 3 if truly uncertain. 0 if not COMBAT."
                    + context_hint
                ),
            },
            {"role": "user", "content": player_input},
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=256)
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

        opponent_name = str(data.get("opponent_name", "")).strip()
        try:
            opponent_power = max(1, min(10, int(data.get("opponent_power", 3))))
        except (TypeError, ValueError):
            opponent_power = 3

        return mode, {
            "mode": mode.value,
            "ambush": bool(data.get("ambush", False)),
            "narrative_time_seconds": seconds,
            "opponent_name": opponent_name,
            "opponent_power": opponent_power,
        }

    @staticmethod
    def _length_instruction(max_tokens: int) -> str:
        """Return a length constraint instruction scaled to the token budget.

        Uses approximate word counts (1 token ≈ 0.6 words for Portuguese) to give the model
        a concrete, hard-to-ignore limit for the narrative_text field only.
        """
        # Approximate word budget for narrative (tokens * 0.75 words/token)
        word_budget = int(max_tokens * 0.6)
        if max_tokens <= 512:
            return (
                f"HARD LENGTH LIMIT: The 'narrative_text' field MUST be under {word_budget} words "
                f"(~{max_tokens} tokens). This is 1-2 short paragraphs. "
                "Be concise but complete. Always end at a natural stopping point. "
                "Going over this limit is a FAILURE — trim ruthlessly."
            )
        if max_tokens <= 1000:
            return (
                f"HARD LENGTH LIMIT: The 'narrative_text' field MUST be under {word_budget} words "
                f"(~{max_tokens} tokens). This is 2-4 paragraphs. "
                "Focus on the most important narrative beats. Always end at a natural stopping point. "
                "Going over this limit is a FAILURE — trim ruthlessly."
            )
        if max_tokens <= 1500:
            return (
                f"HARD LENGTH LIMIT: The 'narrative_text' field MUST be under {word_budget} words "
                f"(~{max_tokens} tokens). This is 4-6 paragraphs. "
                "Always end at a natural stopping point with a clear prompt for the player. "
                "Going over this limit is a FAILURE — trim ruthlessly."
            )
        if max_tokens <= 3000:
            return (
                f"LENGTH GUIDELINE: Aim for under {word_budget} words (~{max_tokens} tokens) "
                "in the 'narrative_text' field. Write rich prose but don't ramble. "
                "Always end at a natural stopping point."
            )
        return ""

    _NARRATOR_RULES = {
        "en": (
            "\nNARRATOR RULES:\n"
            "- Write immersive, evocative prose. Never break character.\n"
            "- React meaningfully to player choices. Consequences are real.\n"
            "- The world is alive — NPCs have their own agendas and memories.\n"
            "- ALWAYS use FULL character names (first + last) in narration. You may use short names in dialogue spoken by characters, but the narration itself must use full names.\n"
            "- When mentioning a character by name in narration, prefix their name with @ (e.g. @Satoru Gojo). This applies to ALL named characters and NPCs. Do NOT use @ in dialogue lines spoken by characters, only in narration text.\n"
            "- Stay consistent with the established tone.\n"
            "- Do NOT summarize. Narrate in present tense.\n"
            "- End each response at a natural pause, not mid-action.\n"
            "- ALWAYS finish your response with a complete sentence. Never stop mid-word or mid-sentence.\n"
            "{length_instruction}"
            "- When the player ACQUIRES an item, emit: [ITEM_ADD:item_name|category|source_description]\n"
            "- When an item is CONSUMED or EXPENDED, emit: [ITEM_USE:item_name]\n"
            "- When an item is LOST, STOLEN, or DESTROYED, emit: [ITEM_LOSE:item_name]\n"
            "- Categories: weapon, armor, consumable, quest, tool, misc\n"
            "- If the player tries to use an item NOT in their inventory, reject the action narratively.\n"
            "- Place item tags at the end of the relevant sentence, inline with the narrative.\n"
            "- IMPORTANT: If you mention an item from the WORLD LORE / story cards that the player is carrying or using for the FIRST TIME in the story (e.g. a keepsake, a weapon described in the scenario), emit [ITEM_ADD] for it so it appears in the inventory. Story card items that the player already has but haven't been registered yet MUST be tagged.\n"
        ),
        "pt-br": (
            "\nREGRAS DO NARRADOR:\n"
            "- Escreva prosa imersiva e evocativa. Nunca quebre o personagem.\n"
            "- Reaja de forma significativa às escolhas do jogador. Consequências são reais.\n"
            "- O mundo é vivo — NPCs têm suas próprias agendas e memórias.\n"
            "- SEMPRE use nomes COMPLETOS dos personagens (nome + sobrenome) na narração. Nomes curtos são permitidos apenas em diálogos falados pelos personagens, mas a narração em si deve usar nomes completos.\n"
            "- Ao mencionar um personagem pelo nome na narração, prefixe com @ (ex: @Satoru Gojo). Isso se aplica a TODOS os personagens e NPCs nomeados. NÃO use @ em falas de diálogo dos personagens, apenas no texto narrativo.\n"
            "- Mantenha consistência com o tom estabelecido.\n"
            "- NÃO resuma. Narre no tempo presente.\n"
            "- Termine cada resposta em uma pausa natural, não no meio de uma ação.\n"
            "- SEMPRE termine sua resposta com uma frase completa. Nunca pare no meio de uma palavra ou frase.\n"
            "{length_instruction}"
            "- Quando o jogador ADQUIRIR um item, emita: [ITEM_ADD:nome_item|categoria|descrição_origem]\n"
            "- Quando um item for CONSUMIDO ou GASTO, emita: [ITEM_USE:nome_item]\n"
            "- Quando um item for PERDIDO, ROUBADO ou DESTRUÍDO, emita: [ITEM_LOSE:nome_item]\n"
            "- Categorias: weapon, armor, consumable, quest, tool, misc\n"
            "- Se o jogador tentar usar um item que NÃO está no inventário, rejeite a ação narrativamente.\n"
            "- Coloque as tags de item no final da frase relevante, inline com a narrativa.\n"
            "- IMPORTANTE: Se você mencionar um item do WORLD LORE / story cards que o jogador está carregando ou usando PELA PRIMEIRA VEZ na história (ex: um amuleto, uma arma descrita no cenário), emita [ITEM_ADD] para que apareça no inventário. Itens de story cards que o jogador já possui mas ainda não foram registrados DEVEM ser taggeados.\n"
        ),
    }

    def _build_narrator_rules(self, max_tokens: int, language: str = "en") -> str:
        """Build the static narrator rules block in the appropriate language."""
        length_instruction = self._length_instruction(max_tokens)
        length_line = f"- {length_instruction}\n" if length_instruction else ""
        template = self._NARRATOR_RULES.get(language, self._NARRATOR_RULES["en"])
        return template.format(length_instruction=length_line)

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

        sections.append(self._build_narrator_rules(max_tokens, language))
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
        static_sections.append(self._build_narrator_rules(max_tokens, language))
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
        memory_context: str = "",
        inventory_context: str = "",
        journal_context: str = "",
        npc_context: str = "",
        graph_context: str = "",
        story_cards_context: str = "",
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
            "- Use ONLY the provided world data to answer. Do NOT invent or guess facts.",
        ]
        if memory_context:
            sections.append(f"\nWORLD MEMORY:\n{memory_context}")
        if inventory_context:
            sections.append(f"\n{inventory_context}")
        if journal_context:
            sections.append(f"\nJOURNAL (recent entries):\n{journal_context}")
        if npc_context:
            sections.append(f"\nACTIVE NPCs:\n{npc_context}")
        if graph_context:
            sections.append(f"\nWORLD RELATIONSHIPS:\n{graph_context}")
        if story_cards_context:
            sections.append(f"\n{story_cards_context}")
        return "\n".join(sections)

    # Hard cap on history messages sent to the LLM.
    # The crystal memory pyramid handles long-term context, so we only need
    # recent exchanges for narrative continuity and tone consistency.
    MAX_HISTORY_MESSAGES = 25  # ~12 exchanges + 1 user message

    @staticmethod
    def _dynamic_history_slice(history: list[dict], context_window: int, system_tokens: int) -> list[dict]:
        """Return recent history messages, capped at MAX_HISTORY_MESSAGES.

        The crystal memory pyramid (SHORT→MEDIUM→LONG→MEMORY) in the system
        prompt provides long-term context.  The history slice only needs to
        cover the most recent exchanges for narrative flow and tone.

        Budget allocation:
        - Hard cap: MAX_HISTORY_MESSAGES (newest messages)
        - Then: fit within (context_window - system_tokens - output_reserve)
        - Minimum: 4 messages (2 exchanges) for coherence
        """
        max_msgs = NarratorEngine.MAX_HISTORY_MESSAGES
        output_reserve = 2500
        budget = context_window - system_tokens - output_reserve
        if budget <= 0:
            return history[-4:]

        # Start from the most recent messages, capped at max_msgs
        candidates = history[-max_msgs:] if len(history) > max_msgs else history

        # Further trim by token budget
        selected: list[dict] = []
        used = 0
        for msg in reversed(candidates):
            msg_tokens = estimate_tokens(msg.get("content", ""))
            if used + msg_tokens > budget:
                break
            selected.append(msg)
            used += msg_tokens
        selected.reverse()

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

        # Debug logging: log full LLM request context
        logger.debug(
            "=== NARRATOR STREAM REQUEST ===\n"
            "System prompt (%d tokens, %d chars):\n%s\n"
            "History slice: %d messages (of %d total)\n"
            "Player input: %s\n"
            "Context window: %d",
            system_tokens, len(system_prompt), system_prompt,
            len(history_slice), len(history),
            player_input,
            context_window,
        )
        if logger.isEnabledFor(logging.DEBUG):
            for idx, msg in enumerate(history_slice):
                content = msg.get("content", "")
                logger.debug(
                    "  History[%d] role=%s len=%d: %s",
                    idx, msg.get("role", "?"), len(content),
                    content[:200] + ("..." if len(content) > 200 else ""),
                )

        full_response = ""
        try:
            async for chunk in self._llm.stream(messages=messages):
                full_response += chunk
                yield chunk
        except Exception:
            yield self._fallback_narrative(player_input)

        # Debug logging: log full response
        logger.debug(
            "=== NARRATOR STREAM RESPONSE ===\n"
            "Response length: %d chars\n%s",
            len(full_response),
            full_response[:500] + ("..." if len(full_response) > 500 else ""),
        )

    _SINGLE_CALL_FORMAT = (
        "\n\n=== RESPONSE FORMAT ===\n"
        "You MUST return ONLY valid JSON (no markdown fences) with this exact schema:\n"
        "{\n"
        '  "mode": "NARRATIVE|COMBAT|META",\n'
        '  "narrative_time_seconds": <int, realistic story time this action takes>,\n'
        '  "ambush": <bool, true only if NPC attacks player by surprise>,\n'
        '  "narrative_text": "<your full narrative prose response — MUST respect the word limit from LENGTH instructions>",\n'
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
        "- The narrative_text must be complete, immersive prose — not a summary.\n"
        "- CRITICAL: The narrative_text MUST stay within the word/token limit specified in the LENGTH instructions above. "
        "The other JSON fields (npc_thoughts, entities, etc.) do NOT count toward that limit — only narrative_text does."
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

        # Debug logging: log full single-call LLM request context
        logger.debug(
            "=== NARRATOR SINGLE-CALL REQUEST ===\n"
            "Static prompt (%d chars): %s\n"
            "Dynamic prompt (%d chars): %s\n"
            "History slice: %d messages (of %d total)\n"
            "Player input: %s\n"
            "Context window: %d, max_tokens: %d",
            len(cached_text), cached_text[:300] + ("..." if len(cached_text) > 300 else ""),
            len(dynamic_text), dynamic_text[:500] + ("..." if len(dynamic_text) > 500 else ""),
            len(history_slice), len(history),
            player_input,
            context_window, max_tokens,
        )
        if logger.isEnabledFor(logging.DEBUG):
            for idx, msg in enumerate(history_slice):
                content = msg.get("content", "")
                logger.debug(
                    "  History[%d] role=%s len=%d: %s",
                    idx, msg.get("role", "?"), len(content),
                    content[:200] + ("..." if len(content) > 200 else ""),
                )

        try:
            # User's narrative budget + 1500 tokens overhead for JSON metadata
            api_max_tokens = max_tokens + 1500
            raw = await self._llm.complete(messages=messages, max_tokens=api_max_tokens)

            # Debug logging: log full response
            logger.debug(
                "=== NARRATOR SINGLE-CALL RESPONSE ===\n"
                "Response length: %d chars\n%s",
                len(raw) if raw else 0,
                (raw or "")[:500] + ("..." if raw and len(raw) > 500 else ""),
            )

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
            "opponent_name": "",
            "opponent_power": 3,
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
