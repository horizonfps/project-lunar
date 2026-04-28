from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from app.utils.json_parsing import parse_json_dict


@dataclass
class NpcThought:
    key: str
    value: str
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class NpcMind:
    name: str
    campaign_id: str
    thoughts: dict[str, NpcThought] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    def set_thought(self, key: str, value: str):
        self.thoughts[key] = NpcThought(key=key, value=value)

    def get_thought(self, key: str) -> str | None:
        t = self.thoughts.get(key)
        return t.value if t else None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "campaign_id": self.campaign_id,
            "aliases": self.aliases,
            "thoughts": {
                k: {"value": t.value, "updated_at": t.updated_at}
                for k, t in self.thoughts.items()
            },
        }


def _is_generic_npc_name(name: str) -> bool:
    """Return True if the name looks like a generic/unnamed NPC description.

    Generic names are role/appearance descriptions rather than proper names,
    e.g. 'young servant', 'gate guardian', 'first raider'.
    """
    import re
    n = name.lower().strip()

    # Ordinal prefixes: "primeiro saqueador", "second guard", "terceiro bandido"
    ordinal_pt = r"^(primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa]|sétim[oa]|oitav[oa]|non[oa]|décim[oa])\b"
    ordinal_en = r"^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b"
    if re.search(ordinal_pt, n) or re.search(ordinal_en, n):
        return True

    # Common generic role/descriptor words (pt-br and en)
    generic_markers_pt = [
        "servo", "serva", "guarda", "guardião", "guardiã", "soldado", "cavaleiro",
        "mercador", "mercadora", "comerciante", "aldeão", "aldeã", "camponês", "camponesa",
        "saqueador", "saqueadora", "bandido", "bandida", "ladrão", "ladra",
        "figura", "viajante", "mendigo", "mendiga", "escravo", "escrava",
        "sacerdote", "sacerdotisa", "monge", "monja", "criança", "velho", "velha",
        "jovem", "ancião", "anciã", "ferreiro", "ferreira", "taberneiro", "taberneira",
        "barqueiro", "barqueira", "mensageiro", "mensageira", "espião", "espiã",
        "capitão", "capitã", "tenente", "sargento", "arqueiro", "arqueira",
        "mago", "maga", "feiticeiro", "feiticeira", "curandeiro", "curandeira",
    ]
    generic_markers_en = [
        "servant", "guard", "guardian", "soldier", "knight", "merchant", "trader",
        "villager", "peasant", "raider", "bandit", "thief", "figure", "traveler",
        "beggar", "slave", "priest", "priestess", "monk", "nun", "child", "elder",
        "old", "young", "blacksmith", "innkeeper", "bartender", "messenger", "spy",
        "captain", "lieutenant", "sergeant", "archer", "mage", "sorcerer", "sorceress",
        "healer", "hooded", "masked", "cloaked", "stranger",
    ]

    words = set(re.split(r"\s+", n))
    # If ALL words in the name are generic markers or short connectors, it's generic
    connectors = {"do", "da", "dos", "das", "de", "o", "a", "os", "as", "the", "of"}
    all_markers = set(generic_markers_pt + generic_markers_en) | connectors
    if words and words.issubset(all_markers):
        return True

    return False


class NpcMindEngine:
    def __init__(self, llm):
        self._llm = llm
        self._minds: dict[str, dict[str, NpcMind]] = {}  # campaign_id -> {npc_name -> NpcMind}

    def get_mind(self, campaign_id: str, npc_name: str) -> NpcMind | None:
        return self._minds.get(campaign_id, {}).get(npc_name.lower())

    def get_all_minds(self, campaign_id: str) -> list[NpcMind]:
        return list(self._minds.get(campaign_id, {}).values())

    def _find_alias_match(self, campaign_id: str, name: str) -> NpcMind | None:
        """Check if name is already a known alias of an existing NPC."""
        minds = self._minds.get(campaign_id, {})
        name_lower = name.lower()
        for mind in minds.values():
            if name_lower in [a.lower() for a in mind.aliases]:
                return mind
        return None

    def _find_fuzzy_candidates(self, campaign_id: str, name: str, threshold: float = 0.6) -> list[NpcMind]:
        """Find existing NPCs with fuzzy-similar names.

        Uses two tiers:
        1. Substring containment — guaranteed candidate (e.g. "Gojo" in "Satoru Gojo")
        2. Fuzzy ratio >= threshold — probable candidate
        All candidates go through LLM confirmation.
        """
        from difflib import SequenceMatcher
        minds = self._minds.get(campaign_id, {})
        name_lower = name.lower()
        candidates = []
        seen_keys: set[str] = set()
        for key, mind in minds.items():
            if key == name_lower:
                continue
            # Tier 1: substring containment — guaranteed candidate (e.g. "Gojo" in "Satoru Gojo")
            all_names = [key] + [a.lower() for a in mind.aliases]
            substring_match = any(
                name_lower in n or n in name_lower
                for n in all_names
                if len(n) >= 2 and len(name_lower) >= 2  # avoid single-char matches
            )
            if substring_match and key not in seen_keys:
                candidates.append(mind)
                seen_keys.add(key)
                continue
            # Tier 2: fuzzy ratio
            ratio = SequenceMatcher(None, name_lower, key).ratio()
            if ratio >= threshold and key not in seen_keys:
                candidates.append(mind)
                seen_keys.add(key)
            else:
                for alias in mind.aliases:
                    if SequenceMatcher(None, name_lower, alias.lower()).ratio() >= threshold and key not in seen_keys:
                        candidates.append(mind)
                        seen_keys.add(key)
                        break
        return candidates

    async def _confirm_same_character(
        self, name_a: str, name_b: str, context_a: str = "", context_b: str = ""
    ) -> bool:
        """Ask LLM if two names refer to the same character, with optional context."""
        context_info = ""
        if context_a:
            context_info += f"\nContext for '{name_a}': {context_a}"
        if context_b:
            context_info += f"\nContext for '{name_b}': {context_b}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You determine if two character names refer to the same character in an RPG. "
                    "Consider name order variations (e.g. 'FirstName LastName' = 'LastName FirstName'), "
                    "nicknames, titles, and partial names. "
                    "Answer ONLY 'YES' or 'NO'."
                ),
            },
            {
                "role": "user",
                "content": f"Are these the same character?\nName A: {name_a}\nName B: {name_b}{context_info}",
            },
        ]
        raw = await self._llm.complete(messages=messages, max_tokens=16)
        return raw.strip().upper().startswith("YES")

    def _ensure_mind(self, campaign_id: str, npc_name: str) -> NpcMind:
        # Strip @ prefix that narration uses for mentions (e.g. "@Yuji Itadori" → "Yuji Itadori")
        npc_name = npc_name.lstrip("@").strip()
        if campaign_id not in self._minds:
            self._minds[campaign_id] = {}
        key = npc_name.lower()
        if key not in self._minds[campaign_id]:
            alias_match = self._find_alias_match(campaign_id, npc_name)
            if alias_match:
                return alias_match
            self._minds[campaign_id][key] = NpcMind(name=npc_name, campaign_id=campaign_id)
        return self._minds[campaign_id][key]

    async def _ensure_mind_async(self, campaign_id: str, npc_name: str) -> NpcMind:
        """Like _ensure_mind but with fuzzy matching + LLM confirmation."""
        # Strip @ prefix that narration uses for mentions
        npc_name = npc_name.lstrip("@").strip()
        if campaign_id not in self._minds:
            self._minds[campaign_id] = {}
        key = npc_name.lower()
        if key in self._minds[campaign_id]:
            return self._minds[campaign_id][key]

        alias_match = self._find_alias_match(campaign_id, npc_name)
        if alias_match:
            return alias_match

        candidates = self._find_fuzzy_candidates(campaign_id, npc_name)
        for candidate in candidates:
            if await self._confirm_same_character(npc_name, candidate.name):
                if npc_name.lower() not in [a.lower() for a in candidate.aliases]:
                    candidate.aliases.append(npc_name)
                if len(npc_name) > len(candidate.name):
                    old_key = candidate.name.lower()
                    candidate.name = npc_name
                    # Re-key: move entry from short name to full name
                    minds = self._minds[campaign_id]
                    if old_key in minds:
                        del minds[old_key]
                    minds[npc_name.lower()] = candidate
                return candidate

        self._minds[campaign_id][key] = NpcMind(name=npc_name, campaign_id=campaign_id)
        return self._minds[campaign_id][key]

    def delete_mind(self, campaign_id: str, npc_name: str) -> bool:
        """Delete an NPC mind from memory. Returns True if found and deleted."""
        minds = self._minds.get(campaign_id, {})
        key = npc_name.lower()
        if key in minds:
            del minds[key]
            return True
        # Check aliases
        for k, mind in list(minds.items()):
            if npc_name.lower() in [a.lower() for a in mind.aliases]:
                del minds[k]
                return True
        return False

    def update_thought(self, campaign_id: str, npc_name: str, thought_key: str, value: str) -> NpcMind | None:
        """Update a single thought for an NPC. Returns the updated mind or None."""
        mind = self.get_mind(campaign_id, npc_name)
        if not mind:
            # Check aliases
            minds = self._minds.get(campaign_id, {})
            for m in minds.values():
                if npc_name.lower() in [a.lower() for a in m.aliases]:
                    mind = m
                    break
        if mind:
            mind.set_thought(thought_key, value)
        return mind

    async def update_npc_thoughts(
        self,
        campaign_id: str,
        narrative_text: str,
        world_context: str,
        language: str = "en",
        recent_history: list[dict] | None = None,
    ) -> list[NpcMind]:
        """Analyze narrative and update NPC thoughts based on recent events.

        Args:
            recent_history: Optional list of {role, content} message dicts from
                the immediate conversation. Used so NPCs can reason about what
                actually happened in recent turns (e.g. that the player was
                personally hired by the NPC), not just from compressed crystals.
        """
        _NPC_MIND_PROMPTS = {
            "en": (
                "You analyze RPG narrative text and extract NPC internal thoughts. "
                "For each NPC mentioned, determine what they are privately thinking. "
                "Return ONLY valid JSON (no markdown): "
                '{"npcs": [{"name": str, "thoughts": {"feeling": str, "goal": str, '
                '"opinion_of_player": str, "secret_plan": str}}]}. '
                "Include ALL NPCs that actively appear in the narrative — speaking, acting, "
                "reacting, observing, or being directly described. Also include NPCs that are "
                "physically present in the scene even if they are silent observers — their "
                "internal reaction to what is happening matters. Do NOT skip NPCs just because "
                "others are more prominent in the scene. Aim for completeness over brevity. "
                "Do NOT include NPCs that are only mentioned by other characters or "
                "referenced in memories/flashbacks — only those physically present "
                "in the current scene. "
                "IMPORTANT: Only include NPCs with proper names (e.g. 'Satoru Gojo', 'Yuji'). "
                "Do NOT include generic unnamed characters described only by their role or appearance "
                "(e.g. 'young servant', 'gate guardian', 'first raider', 'hooded figure', 'old merchant'). "
                "These background characters do not get internal thoughts. "
                "Thoughts should reflect their personality and recent events. "
                "Preserve NPC names exactly as they appear in the narrative."
            ),
            "pt-br": (
                "Você analisa texto narrativo de RPG e extrai os pensamentos internos dos NPCs. "
                "Para cada NPC mencionado, determine o que eles estão pensando em privado. "
                "Retorne APENAS JSON válido (sem markdown): "
                '{"npcs": [{"name": str, "thoughts": {"feeling": str, "goal": str, '
                '"opinion_of_player": str, "secret_plan": str}}]}. '
                "Inclua TODOS os NPCs que aparecem ativamente na narrativa — falando, agindo, "
                "reagindo, observando, ou sendo diretamente descritos. Também inclua NPCs que "
                "estão fisicamente presentes na cena mesmo que sejam observadores silenciosos — "
                "a reação interna deles ao que está acontecendo importa. NÃO pule NPCs só porque "
                "outros são mais proeminentes na cena. Priorize completude sobre brevidade. "
                "NÃO inclua NPCs que são apenas mencionados por outros personagens ou "
                "referenciados em memórias/flashbacks — apenas aqueles fisicamente presentes "
                "na cena atual. "
                "IMPORTANTE: Inclua APENAS NPCs com nomes próprios (ex: 'Satoru Gojo', 'Yuji'). "
                "NÃO inclua personagens genéricos sem nome descritos apenas por papel ou aparência "
                "(ex: 'servo jovem', 'guardião do portão', 'primeiro saqueador', 'figura encapuzada', "
                "'mercador velho'). Personagens de fundo não recebem pensamentos internos. "
                "Os pensamentos devem refletir a personalidade deles e eventos recentes. "
                "Preserve os nomes dos NPCs exatamente como aparecem na narrativa. "
                "Escreva todos os valores de pensamento em português brasileiro."
            ),
        }

        prompt_text = _NPC_MIND_PROMPTS.get(language, _NPC_MIND_PROMPTS["en"])
        if language and language != "en" and language not in _NPC_MIND_PROMPTS:
            prompt_text += f" Write all thought values in the same language as the narrative ({language})."

        history_block = ""
        if recent_history:
            lines: list[str] = []
            for msg in recent_history:
                role = msg.get("role", "?")
                content = str(msg.get("content", "")).strip()
                if not content:
                    continue
                speaker = "PLAYER" if role == "user" else ("NARRATOR" if role == "assistant" else role.upper())
                lines.append(f"[{speaker}] {content}")
            if lines:
                history_block = "Recent dialogue and actions (most recent last):\n" + "\n\n".join(lines) + "\n\n"

        user_content = (
            f"World context (compressed long-term memory):\n{world_context}\n\n"
            f"{history_block}"
            f"Latest narrator response (this is the scene to analyze):\n{narrative_text}"
        )
        messages = [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": user_content},
        ]
        raw = await self._llm.complete(messages=messages, max_tokens=4096)
        updated = []
        data = parse_json_dict(raw) or {}
        for npc_data in data.get("npcs", []):
            name = npc_data.get("name", "").lstrip("@").strip()
            if not name:
                continue
            if _is_generic_npc_name(name):
                continue

            # Check for known alias first (no LLM call needed)
            alias_match = self._find_alias_match(campaign_id, name)
            if alias_match:
                mind = alias_match
            else:
                # Check fuzzy match against existing names
                candidates = self._find_fuzzy_candidates(campaign_id, name)
                merged = False
                for candidate in candidates:
                    if await self._confirm_same_character(name, candidate.name):
                        if name.lower() not in [a.lower() for a in candidate.aliases]:
                            candidate.aliases.append(name)
                        if len(name) > len(candidate.name):
                            old_key = candidate.name.lower()
                            candidate.name = name
                            # Re-key: move entry from short name to full name
                            minds = self._minds[campaign_id]
                            if old_key in minds:
                                del minds[old_key]
                            minds[name.lower()] = candidate
                        mind = candidate
                        merged = True
                        break
                if not merged:
                    mind = self._ensure_mind(campaign_id, name)

            for key, value in npc_data.get("thoughts", {}).items():
                if value:
                    mind.set_thought(key, str(value))
            updated.append(mind)
        return updated
