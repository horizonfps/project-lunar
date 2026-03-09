from __future__ import annotations

from app.db.scenario_store import ScenarioStore, StoryCard, StoryCardType
from app.utils.json_parsing import parse_json_list


class ScenarioService:
    def __init__(self, store: ScenarioStore, llm):
        self.store = store
        self._llm = llm

    async def extract_lore_to_cards(
        self,
        scenario_id: str,
        lore_text: str,
    ) -> list[StoryCard]:
        if not lore_text.strip():
            return []

        messages = [
            {
                "role": "system",
                "content": (
                    "Extract all named entities from this RPG world lore text. "
                    "Return ONLY a valid JSON array (no markdown): "
                    '[{"type": "NPC|LOCATION|FACTION|ITEM", "name": str, "content": {...}}]. '
                    "For NPC content include: personality, power_level (1-10), secret. "
                    "For LOCATION content include: description. "
                    "For FACTION content include: goals, power_level. "
                    "For ITEM content include: description, significance. "
                    "Only include entities explicitly mentioned by name."
                ),
            },
            {"role": "user", "content": lore_text},
        ]
        raw = await self._llm.complete(messages=messages)
        entities = parse_json_list(raw)
        if entities is None:
            return []

        cards: list[StoryCard] = []
        for entity in entities:
            try:
                card_type = StoryCardType(entity["type"])
                card = self.store.add_story_card(
                    scenario_id=scenario_id,
                    card_type=card_type,
                    name=entity["name"],
                    content=entity.get("content", {}),
                )
                cards.append(card)
            except (KeyError, ValueError, TypeError):
                continue

        return cards
