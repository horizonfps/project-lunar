from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.utils.json_parsing import parse_json_dict


class JournalCategory(str, Enum):
    DISCOVERY = "DISCOVERY"
    RELATIONSHIP_CHANGE = "RELATIONSHIP_CHANGE"
    COMBAT = "COMBAT"
    DECISION = "DECISION"
    WORLD_EVENT = "WORLD_EVENT"


@dataclass
class JournalEntry:
    campaign_id: str
    category: JournalCategory
    summary: str
    created_at: str


class JournalEngine:
    def __init__(self, llm, event_store=None):
        self._llm = llm
        self._event_store = event_store
        self._journals: dict[str, list[JournalEntry]] = {}

    async def evaluate_and_log(
        self,
        campaign_id: str,
        narrative_text: str,
    ) -> JournalEntry | None:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a journal keeper for an RPG game. Evaluate if this narrative moment should be logged. "
                    "Be GENEROUS — most narrative moments with named NPCs, fights, locations, or choices ARE significant. "
                    "Categories:\n"
                    "- DISCOVERY: learning secrets, finding new locations/items, uncovering lore\n"
                    "- RELATIONSHIP_CHANGE: any meaningful NPC interaction — alliances, betrayals, deals, trust shifts\n"
                    "- COMBAT: any fight, attack, defense, escape from danger, or combat outcome\n"
                    "- DECISION: player choices that affect the story — agreements, refusals, strategic decisions\n"
                    "- WORLD_EVENT: external events, faction movements, world changes\n"
                    "Only skip truly mundane description with no named entities or actions. "
                    "Return ONLY valid JSON (no markdown): "
                    '{"relevant": bool, '
                    '"category": "DISCOVERY|RELATIONSHIP_CHANGE|COMBAT|DECISION|WORLD_EVENT|null", '
                    '"summary": "one sentence summary or null"}'
                ),
            },
            {"role": "user", "content": narrative_text},
        ]
        try:
            raw = await self._llm.complete(messages=messages)
            data = parse_json_dict(raw)
        except Exception:
            data = None
        inferred_category = self._infer_category(narrative_text)
        inferred_summary = self._fallback_summary(narrative_text)

        category: JournalCategory | None = None
        summary: str | None = None

        if data and data.get("relevant"):
            summary = data.get("summary") or inferred_summary
            category_raw = data.get("category")
            if category_raw:
                try:
                    category = JournalCategory(category_raw)
                except ValueError:
                    category = None

        # Heuristic fallback when model output is missing/inconsistent.
        if inferred_category and (category is None or category == JournalCategory.DISCOVERY):
            category = inferred_category

        if not category:
            return None
        if not summary:
            summary = inferred_summary

        return self._append_entry(campaign_id, category, summary)

    def get_journal(self, campaign_id: str) -> list[JournalEntry]:
        return self._journals.get(campaign_id, [])

    def get_by_category(
        self, campaign_id: str, category: JournalCategory
    ) -> list[JournalEntry]:
        return [
            e for e in self.get_journal(campaign_id)
            if e.category == category
        ]

    def log_player_action(self, campaign_id: str, action_text: str) -> JournalEntry | None:
        """Deterministic lightweight logging for explicit player intent actions."""
        category = self._infer_category(action_text)
        if category not in {JournalCategory.DECISION, JournalCategory.RELATIONSHIP_CHANGE}:
            return None
        summary = self._fallback_summary(action_text)
        return self._append_entry(campaign_id, category, summary)

    @staticmethod
    def _infer_category(text: str) -> JournalCategory | None:
        t = text.lower()

        def has_any(keywords: tuple[str, ...]) -> bool:
            for keyword in keywords:
                if " " in keyword:
                    if keyword in t:
                        return True
                else:
                    if re.search(rf"\b{re.escape(keyword)}\b", t):
                        return True
            return False

        combat_keywords = (
            "attack", "strike", "slash", "parry", "fight", "combat", "wound",
            "defeat", "surrender", "ambush", "duel",
        )
        if has_any(combat_keywords):
            return JournalCategory.COMBAT

        decision_keywords = (
            "choose", "decide", "refuse", "accept", "demand", "offer", "agree",
            "plan", "vow", "swear", "commit", "choice", "last chance", "your move", "you can",
        )
        if has_any(decision_keywords):
            return JournalCategory.DECISION

        relationship_keywords = (
            "ask", "tell", "warn", "ally", "betray", "trust", "guard", "npc",
            "negotiate", "deal", "threaten", "promise",
        )
        if has_any(relationship_keywords):
            return JournalCategory.RELATIONSHIP_CHANGE

        world_keywords = (
            "time passes", "world", "faction", "rebellion", "kingdom", "war",
            "rumor", "capital", "legion", "citadel", "political",
        )
        if has_any(world_keywords):
            return JournalCategory.WORLD_EVENT

        discovery_keywords = (
            "discover", "find", "reveal", "secret", "hidden", "learn", "map",
            "lore", "clue",
        )
        if has_any(discovery_keywords):
            return JournalCategory.DISCOVERY

        return None

    @staticmethod
    def _fallback_summary(text: str) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) > 180:
            return cleaned[:177] + "..."
        return cleaned

    def _append_entry(
        self,
        campaign_id: str,
        category: JournalCategory,
        summary: str,
    ) -> JournalEntry:
        entry = JournalEntry(
            campaign_id=campaign_id,
            category=category,
            summary=summary,
            created_at=datetime.utcnow().isoformat(),
        )
        if campaign_id not in self._journals:
            self._journals[campaign_id] = []
        self._journals[campaign_id].append(entry)
        # Persist to event store so journal survives restarts
        if self._event_store:
            from app.db.event_store import EventType
            self._event_store.append(
                campaign_id=campaign_id,
                event_type=EventType.JOURNAL_ENTRY,
                payload={
                    "category": category.value,
                    "summary": summary,
                },
                narrative_time_delta=0,
                location="journal",
                entities=[],
            )
        return entry
