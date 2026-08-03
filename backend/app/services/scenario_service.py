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
        language: str = "en",
    ) -> list[StoryCard]:
        if not lore_text.strip():
            return []

        lang_hint = ""
        if language and language != "en":
            lang_map = {
                "pt-br": "Portuguese (Brazilian)",
                "pt": "Portuguese",
                "es": "Spanish",
                "fr": "French",
                "de": "German",
                "ja": "Japanese",
                "ko": "Korean",
                "zh": "Chinese",
            }
            lang_name = lang_map.get(language, language)
            lang_hint = f" IMPORTANT: The lore text is in {lang_name}. Preserve all names in their original language and write ALL content fields (personality, description, goals, secret, significance) in {lang_name}."

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
                    + lang_hint
                ),
            },
            {"role": "user", "content": lore_text},
        ]
        raw = await self._llm.complete(messages=messages, max_tokens=2048, reasoning=False)
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
