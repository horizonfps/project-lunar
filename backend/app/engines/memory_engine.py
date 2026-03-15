from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum

from app.db.event_store import EventStore, Event, EventType
from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


class CrystalTier(str, Enum):
    SHORT = "SHORT"   # Last few sessions — compressed
    LONG = "LONG"     # Permanent extracted facts


@dataclass
class MemoryCrystal:
    campaign_id: str
    tier: CrystalTier
    content: str  # Player-facing executive summary
    ai_content: str  # Ultra-compressed memory used in LLM context
    event_count: int
    source_start_created_at: str | None = None
    source_end_created_at: str | None = None


class MemoryEngine:
    RAW_LIMIT = 6
    AUTO_CRYSTALLIZE_THRESHOLD = 8
    MAX_CRYSTALLIZE_EVENTS = 200
    MAX_SHORT_CRYSTALS_IN_CONTEXT = 2
    MAX_LONG_CRYSTALS_IN_CONTEXT = 2
    CRYSTALLIZE_EVENT_TYPES = (
        EventType.PLAYER_ACTION,
        EventType.NARRATOR_RESPONSE,
        EventType.WORLD_TICK,
        EventType.COMBAT_RESULT,
        EventType.TIMESKIP,
    )

    def __init__(self, event_store: EventStore, llm, graphiti_engine=None):
        self._store = event_store
        self._llm = llm
        self._graphiti = graphiti_engine
        self._crystals: dict[str, list[MemoryCrystal]] = {}
        self._crystallizing: set[str] = set()  # prevent concurrent auto-crystallize
        self._last_crystal_cursor: dict[str, str] = {}

    def set_graphiti(self, graphiti_engine) -> None:
        """Set the Graphiti engine for temporal knowledge graph integration."""
        if self._graphiti is None:
            self._graphiti = graphiti_engine

    def get_raw_context(self, campaign_id: str, limit: int = RAW_LIMIT) -> list[Event]:
        return self._store.get_recent(campaign_id, limit=limit)

    async def crystallize(
        self,
        campaign_id: str,
        tier: CrystalTier,
        force: bool = False,
    ) -> MemoryCrystal:
        if tier == CrystalTier.SHORT:
            events = self._get_uncrystallized_events(
                campaign_id,
                limit=self.MAX_CRYSTALLIZE_EVENTS,
            )
            if not events and not force:
                latest = self._latest_crystal(campaign_id, tier)
                if latest:
                    return latest
        else:
            events = self._store.get_recent(campaign_id, limit=self.MAX_CRYSTALLIZE_EVENTS)

        if not events:
            crystal = MemoryCrystal(
                campaign_id=campaign_id,
                tier=tier,
                content="No meaningful updates yet.",
                ai_content="MEM:EMPTY",
                event_count=0,
            )
            self._crystals.setdefault(campaign_id, []).append(crystal)
            return crystal

        events_text = self._format_event_batch(events)
        previous_ai = self._latest_crystal(campaign_id, tier)
        previous_ai_content = previous_ai.ai_content if previous_ai else ""

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a memory crystallizer for an RPG engine.\n"
                    "Return ONLY valid JSON (no markdown) with this schema:\n"
                    '{"ai_memory": str, "player_summary": str}\n\n'
                    "Rules:\n"
                    "- ai_memory: machine-oriented ultra-compact memory for LLM context. "
                    "Use dense abbreviations, avoid filler, avoid repeated facts.\n"
                    "- player_summary: short executive summary for UI (2-4 sentences).\n"
                    "- Preserve decisions, relationship shifts, world state, conflicts, unresolved hooks.\n"
                    "- Focus on net-new changes from NEW_EVENTS; do not restate stable facts unless changed."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"CRYSTAL_TIER: {tier.value}\n"
                    f"PREVIOUS_AI_CRYSTAL:\n{previous_ai_content or '(none)'}\n\n"
                    f"NEW_EVENTS:\n{events_text}"
                ),
            },
        ]

        ai_content = ""
        player_summary = ""
        try:
            raw = await self._llm.complete(messages=prompt)
            parsed = parse_json_dict(raw)
            if parsed:
                ai_content = str(parsed.get("ai_memory", "")).strip()
                player_summary = str(parsed.get("player_summary", "")).strip()
        except Exception:
            logger.warning(
                "LLM crystallization failed for campaign %s, using fallback summary",
                campaign_id,
                exc_info=True,
            )

        if not ai_content:
            ai_content = self._fallback_ai_crystal_summary(events, previous_ai_content)
        if not player_summary:
            player_summary = self._fallback_player_summary(events)

        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=tier,
            content=player_summary,
            ai_content=ai_content,
            event_count=len(events),
            source_start_created_at=events[0].created_at,
            source_end_created_at=events[-1].created_at,
        )
        self._crystals.setdefault(campaign_id, []).append(crystal)
        try:
            self._store.append(
                campaign_id=campaign_id,
                event_type=EventType.MEMORY_CRYSTAL,
                payload={
                    "tier": tier.value,
                    "summary": player_summary,
                    "ai_content": ai_content,
                    "event_count": len(events),
                },
                narrative_time_delta=0,
                location="memory",
                entities=[],
            )
        except Exception:
            logger.warning("Failed to persist memory crystal event for campaign %s", campaign_id, exc_info=True)

        if tier == CrystalTier.SHORT:
            self._last_crystal_cursor[campaign_id] = events[-1].created_at

        return crystal

    async def auto_crystallize_if_needed(self, campaign_id: str) -> MemoryCrystal | None:
        """Auto-crystallize when raw events exceed threshold."""
        if campaign_id in self._crystallizing:
            return None

        pending_events = self._get_uncrystallized_events(
            campaign_id,
            limit=self.AUTO_CRYSTALLIZE_THRESHOLD + 1,
        )
        pending_count = len(pending_events)
        if pending_count < self.AUTO_CRYSTALLIZE_THRESHOLD:
            return None

        self._crystallizing.add(campaign_id)
        try:
            logger.info(
                "Auto-crystallizing %d new events for campaign %s",
                pending_count,
                campaign_id,
            )
            crystal = await self.crystallize(campaign_id, CrystalTier.SHORT, force=False)
            return crystal
        except Exception:
            logger.warning("Auto-crystallization failed for campaign %s", campaign_id, exc_info=True)
            return None
        finally:
            self._crystallizing.discard(campaign_id)

    @staticmethod
    def _fallback_player_summary(events: list[Event]) -> str:
        snippets: list[str] = []
        seen: set[str] = set()
        for event in events[-8:]:
            text = str(event.payload.get("text", "")).strip()
            if text:
                normalized = text.replace("\n", " ")
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                snippets.append(normalized)

        if not snippets:
            return "No significant events were recorded recently."

        joined = " ".join(snippets)
        if len(joined) > 480:
            joined = joined[:477] + "..."
        return joined

    def _fallback_ai_crystal_summary(self, events: list[Event], previous_ai: str = "") -> str:
        compact_lines: list[str] = []
        seen: set[str] = set()

        for event in events[-30:]:
            line = self._event_to_compact_line(event)
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            compact_lines.append(line)

        if not compact_lines:
            return previous_ai or "MEM:EMPTY"

        merged = "|".join(compact_lines)
        if previous_ai:
            merged = f"{previous_ai}|Δ:{merged}"

        if len(merged) > 1200:
            merged = merged[-1200:]
        return merged

    def _event_to_compact_line(self, event: Event) -> str:
        type_code = {
            EventType.PLAYER_ACTION: "PA",
            EventType.NARRATOR_RESPONSE: "NR",
            EventType.WORLD_TICK: "WT",
            EventType.COMBAT_RESULT: "CR",
            EventType.TIMESKIP: "TS",
        }.get(event.event_type, event.event_type.value[:2])

        if event.event_type == EventType.TIMESKIP:
            seconds = int(event.payload.get("seconds", 0) or 0)
            return f"{type_code}:{seconds}s"

        text = str(event.payload.get("text", "")).replace("\n", " ").strip()
        if not text and event.event_type == EventType.COMBAT_RESULT:
            outcome = str(event.payload.get("outcome", "")).strip()
            quality = event.payload.get("quality", "")
            text = f"{outcome}/{quality}"

        if not text:
            return ""

        if len(text) > 160:
            text = text[:157] + "..."
        return f"{type_code}:{text}"

    def _format_event_batch(self, events: list[Event]) -> str:
        lines: list[str] = []
        for event in events:
            compact = self._event_to_compact_line(event)
            if compact:
                lines.append(compact)
        return "\n".join(lines) if lines else "(no relevant events)"

    def _get_uncrystallized_events(self, campaign_id: str, limit: int) -> list[Event]:
        cursor = self._last_crystal_cursor.get(campaign_id)
        return self._store.get_after(
            campaign_id=campaign_id,
            after_created_at=cursor,
            limit=limit,
            event_types=list(self.CRYSTALLIZE_EVENT_TYPES),
        )

    def _latest_crystal(self, campaign_id: str, tier: CrystalTier) -> MemoryCrystal | None:
        for crystal in reversed(self._crystals.get(campaign_id, [])):
            if crystal.tier == tier:
                return crystal
        return None

    def get_crystals(self, campaign_id: str) -> list[MemoryCrystal]:
        return self._crystals.get(campaign_id, [])

    def build_context_window(self, campaign_id: str) -> str:
        parts: list[str] = []

        crystals = self.get_crystals(campaign_id)
        long_crystals = [c for c in crystals if c.tier == CrystalTier.LONG]
        short_crystals = [c for c in crystals if c.tier == CrystalTier.SHORT]

        if long_crystals:
            parts.append("=== PERMANENT_MEMORY_AI ===")
            for c in long_crystals[-self.MAX_LONG_CRYSTALS_IN_CONTEXT:]:
                parts.append(c.ai_content or c.content)

        if short_crystals:
            parts.append("=== RECENT_MEMORY_AI ===")
            for c in short_crystals[-self.MAX_SHORT_CRYSTALS_IN_CONTEXT:]:
                parts.append(c.ai_content or c.content)

        raw_tail = self._get_uncrystallized_events(campaign_id, limit=self.RAW_LIMIT)
        if raw_tail:
            parts.append("=== UNCRYSTALLIZED_DELTA ===")
            for event in raw_tail:
                compact = self._event_to_compact_line(event)
                if compact:
                    parts.append(compact)

        return "\n".join(parts)

    async def build_context_window_async(self, campaign_id: str) -> str:
        parts: list[str] = []

        crystals = self.get_crystals(campaign_id)
        long_crystals = [c for c in crystals if c.tier == CrystalTier.LONG]
        short_crystals = [c for c in crystals if c.tier == CrystalTier.SHORT]

        if long_crystals:
            parts.append("=== PERMANENT_MEMORY_AI ===")
            for c in long_crystals[-self.MAX_LONG_CRYSTALS_IN_CONTEXT:]:
                parts.append(c.ai_content or c.content)

        if short_crystals:
            parts.append("=== RECENT_MEMORY_AI ===")
            for c in short_crystals[-self.MAX_SHORT_CRYSTALS_IN_CONTEXT:]:
                parts.append(c.ai_content or c.content)

        if self._graphiti:
            raw_tail = self._get_uncrystallized_events(campaign_id, limit=5)
            compact_recent = [self._event_to_compact_line(event) for event in raw_tail]
            recent_text = " ".join(line for line in compact_recent if line)
            if recent_text:
                try:
                    facts = await self._graphiti.search(campaign_id, recent_text, limit=8)
                    if facts:
                        parts.append("=== WORLD FACTS ===")
                        for f in facts:
                            parts.append(f"- {f['fact']}")
                except Exception:
                    pass

        raw_tail = self._get_uncrystallized_events(campaign_id, limit=self.RAW_LIMIT)
        if raw_tail:
            parts.append("=== UNCRYSTALLIZED_DELTA ===")
            for event in raw_tail:
                compact = self._event_to_compact_line(event)
                if compact:
                    parts.append(compact)

        return "\n".join(parts)
