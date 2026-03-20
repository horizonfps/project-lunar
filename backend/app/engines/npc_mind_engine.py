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
        """Find existing NPCs with fuzzy-similar names."""
        from difflib import SequenceMatcher
        minds = self._minds.get(campaign_id, {})
        name_lower = name.lower()
        candidates = []
        for key, mind in minds.items():
            if key == name_lower:
                continue
            ratio = SequenceMatcher(None, name_lower, key).ratio()
            if ratio >= threshold:
                candidates.append(mind)
            else:
                for alias in mind.aliases:
                    if SequenceMatcher(None, name_lower, alias.lower()).ratio() >= threshold:
                        candidates.append(mind)
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
                    "Consider name order variations (e.g. 'Satoru Gojo' = 'Gojo Satoru'), "
                    "nicknames, titles, and partial names. "
                    "Answer ONLY 'YES' or 'NO'."
                ),
            },
            {
                "role": "user",
                "content": f"Are these the same character?\nName A: {name_a}\nName B: {name_b}{context_info}",
            },
        ]
        raw = await self._llm.complete(messages=messages)
        return raw.strip().upper().startswith("YES")

    def _ensure_mind(self, campaign_id: str, npc_name: str) -> NpcMind:
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

    async def update_npc_thoughts(
        self,
        campaign_id: str,
        narrative_text: str,
        world_context: str,
        language: str = "en",
    ) -> list[NpcMind]:
        """Analyze narrative and update NPC thoughts based on recent events."""
        lang_hint = ""
        if language and language != "en":
            lang_hint = f" Write all thought values in the same language as the narrative ({language})."

        messages = [
            {
                "role": "system",
                "content": (
                    "You analyze RPG narrative text and extract NPC internal thoughts. "
                    "For each NPC mentioned, determine what they are privately thinking. "
                    "Return ONLY valid JSON (no markdown): "
                    '{"npcs": [{"name": str, "thoughts": {"feeling": str, "goal": str, '
                    '"opinion_of_player": str, "secret_plan": str}}]}. '
                    "Only include NPCs that actively appear in the narrative. "
                    "Thoughts should reflect their personality and recent events."
                    "Preserve NPC names exactly as they appear in the narrative."
                    + lang_hint
                ),
            },
            {
                "role": "user",
                "content": f"World context:\n{world_context}\n\nRecent narrative:\n{narrative_text}",
            },
        ]
        raw = await self._llm.complete(messages=messages)
        updated = []
        data = parse_json_dict(raw) or {}
        for npc_data in data.get("npcs", []):
            name = npc_data.get("name", "")
            if not name:
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
