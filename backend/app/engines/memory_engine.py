from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from enum import Enum

from app.db.event_store import EventStore, Event, EventType
from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


class CrystalTier(str, Enum):
    SHORT = "SHORT"     # ~4 actions → ultra-compressed recap
    MEDIUM = "MEDIUM"   # 4 SHORTs → consolidated summary
    LONG = "LONG"       # 4 MEDIUMs → high-level arc summary
    MEMORY = "MEMORY"   # 4 LONGs → permanent world facts

    @property
    def consolidation_count(self) -> int:
        """How many of the previous tier are needed to trigger this tier."""
        return 4

    @property
    def previous_tier(self) -> CrystalTier | None:
        _prev = {
            CrystalTier.MEDIUM: CrystalTier.SHORT,
            CrystalTier.LONG: CrystalTier.MEDIUM,
            CrystalTier.MEMORY: CrystalTier.LONG,
        }
        return _prev.get(self)

    @property
    def next_tier(self) -> CrystalTier | None:
        _next = {
            CrystalTier.SHORT: CrystalTier.MEDIUM,
            CrystalTier.MEDIUM: CrystalTier.LONG,
            CrystalTier.LONG: CrystalTier.MEMORY,
        }
        return _next.get(self)


@dataclass
class MemoryCrystal:
    campaign_id: str
    tier: CrystalTier
    content: str           # Player-facing executive summary
    ai_content: str        # Ultra-compressed memory for LLM context
    event_count: int
    consumed: bool = False  # True when consolidated into a higher tier
    source_start_created_at: str | None = None
    source_end_created_at: str | None = None


# ── Compression prompts per tier ────────────────────────────────────
# Each tier consolidates the previous tier into a richer structured-JSON
# memory entry. The format is fact-preserving — proper names, physical
# descriptions, mission details, dialogue intent are kept verbatim. The
# pyramid (SHORT→MEDIUM→LONG→MEMORY) widens scope, not lossiness.

_CRYSTAL_SCHEMA_DOC = (
    "Return ONLY valid JSON (no markdown fences) with this exact schema:\n"
    "{\n"
    '  "ai": {\n'
    '    "events": [\n'
    '      {"who": "<actor names>", "action": "<what they did>", "where": "<location>", "result": "<outcome / state change>"}\n'
    '    ],\n'
    '    "characters": {\n'
    '      "<Character Name>": {\n'
    '        "description": "<physical traits, age, distinguishing features — verbatim from source>",\n'
    '        "state": "<current condition / what just happened to them>",\n'
    '        "relationship_to_player": "<ally|enemy|neutral|hired-by|hired-player|family|...>",\n'
    '        "knows_player_as": "<name/identity the NPC associates with the player>"\n'
    '      }\n'
    '    },\n'
    '    "items": [\n'
    '      {"name": "<item name>", "owner": "<current owner>", "status": "acquired|used|lost|given|destroyed"}\n'
    '    ],\n'
    '    "promises_or_missions": [\n'
    '      "<verbatim text of any open commitment, deal, quest, or threat — include who promised what to whom>"\n'
    '    ],\n'
    '    "world_facts": [\n'
    '      "<lasting facts revealed this scene: location names, faction info, lore, rules>"\n'
    '    ]\n'
    '  },\n'
    '  "summary": "<short human-readable text for the player UI>"\n'
    "}\n"
)

_CRYSTAL_INTEGRITY_RULES = (
    "INTEGRITY RULES (violations are failures):\n"
    "- Preserve proper names EXACTLY as in source. Do not normalize, translate, or abbreviate.\n"
    "- NEVER substitute a character's name with a similar-sounding canonical name from "
    "popular fiction. If the source says 'Lena', the output says 'Lena' — never 'Nami', "
    "'Lana', etc. The same applies to every other name.\n"
    "- Preserve physical descriptions exactly: hair color, eye color, age, height, scars, "
    "clothing, voice traits. These details are critical for narrative continuity.\n"
    "- Preserve mission, quest, and promise details exactly: who hired whom, the target, "
    "the conditions, the payment, the deadline. Open promises must survive consolidation.\n"
    "- When a character introduces themselves or reveals identity, keep the verbatim phrasing.\n"
    "- Do NOT invent details that are not in the source.\n"
    "- Do NOT abbreviate words, drop vowels, or use telegraph-style symbols. Write full words.\n"
    "- Do NOT remove information just because it seems descriptive — descriptions are facts.\n"
)

_CRYSTAL_PROMPTS = {
    CrystalTier.SHORT: (
        "You are a structured memory recorder for an RPG AI engine.\n"
        "Record the recent events into a fact-preserving JSON memory entry.\n\n"
        + _CRYSTAL_SCHEMA_DOC + "\n"
        + _CRYSTAL_INTEGRITY_RULES + "\n"
        "SCOPE for SHORT tier:\n"
        "- Covers ~4 recent actions in a single scene.\n"
        "- Include every named character that appears, even briefly.\n"
        "- Include physical descriptions the first time they are mentioned, and keep them "
        "if mentioned again with new detail.\n"
        "- Include short verbatim quotes when they reveal intent, identity, or plot info.\n"
        "- 'summary': 1-2 short sentences in normal language for the player UI."
    ),
    CrystalTier.MEDIUM: (
        "You are a structured memory consolidator for an RPG AI engine.\n"
        "Merge several SHORT crystal JSON entries into a single MEDIUM-tier consolidated entry.\n"
        "Same schema. Wider scope (multiple scenes / a sub-arc).\n\n"
        + _CRYSTAL_SCHEMA_DOC + "\n"
        + _CRYSTAL_INTEGRITY_RULES + "\n"
        "CONSOLIDATION RULES for MEDIUM tier:\n"
        "- Preserve causal order of events. Group closely-related events into one richer "
        "entry only if they share who/where/result.\n"
        "- Merge per-character entries: if the same character appears across multiple SHORTs, "
        "produce a single entry that keeps every distinct descriptor and the latest known state.\n"
        "- Drop only true duplicates. Do not drop a fact just because it seems minor.\n"
        "- Keep every open promise/mission until it is explicitly resolved.\n"
        "- 'summary': 2-3 sentences in normal language for the player UI."
    ),
    CrystalTier.LONG: (
        "You are a structured memory consolidator for an RPG AI engine.\n"
        "Merge MEDIUM crystal JSON entries into a single LONG-tier story-arc entry.\n"
        "Same schema. Covers a major story arc (dozens of actions).\n\n"
        + _CRYSTAL_SCHEMA_DOC + "\n"
        + _CRYSTAL_INTEGRITY_RULES + "\n"
        "CONSOLIDATION RULES for LONG tier:\n"
        "- Group events into the major beats of the arc, but keep enough specificity that "
        "the narrator can reconstruct what happened.\n"
        "- Keep every named character that appeared, with their key descriptors and final "
        "state at the end of the arc.\n"
        "- Keep every open promise/mission. Mark resolved ones with result in 'state'.\n"
        "- 'summary': 3-4 sentences in normal language for the player UI."
    ),
    CrystalTier.MEMORY: (
        "You are a structured memory consolidator for an RPG AI engine.\n"
        "Merge LONG crystal JSON entries into a single PERMANENT-tier world-facts entry.\n"
        "Same schema. Covers the player's permanent identity, completed arcs, lasting world state.\n\n"
        + _CRYSTAL_SCHEMA_DOC + "\n"
        + _CRYSTAL_INTEGRITY_RULES + "\n"
        "CONSOLIDATION RULES for MEMORY tier:\n"
        "- Keep the player's permanent identity, origin, core abilities, and reputation.\n"
        "- Keep every named character ever met, with their description and final state.\n"
        "- Keep all completed major arcs as one event entry each, with the resolution.\n"
        "- Keep all lasting allies, enemies, and faction standings.\n"
        "- 'summary': 4-5 sentences in normal language for the player UI — full story recap."
    ),
}


class MemoryEngine:
    AUTO_CRYSTALLIZE_THRESHOLD = 4  # events before creating a SHORT crystal
    MAX_CRYSTALLIZE_EVENTS = 200
    CONSOLIDATION_COUNT = 4  # N crystals of tier X → 1 crystal of tier X+1
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
        self._crystallizing: set[str] = set()
        self._last_crystal_cursor: dict[str, str] = {}

    def set_graphiti(self, graphiti_engine) -> None:
        if self._graphiti is None:
            self._graphiti = graphiti_engine

    def get_raw_context(self, campaign_id: str, limit: int = 10) -> list[Event]:
        return self._store.get_recent(campaign_id, limit=limit)

    # ── Crystal accessors ───────────────────────────────────────────

    def get_crystals(self, campaign_id: str) -> list[MemoryCrystal]:
        return self._crystals.get(campaign_id, [])

    def _unconsumed_crystals(self, campaign_id: str, tier: CrystalTier) -> list[MemoryCrystal]:
        """Return crystals of a given tier that haven't been consolidated yet."""
        return [
            c for c in self._crystals.get(campaign_id, [])
            if c.tier == tier and not c.consumed
        ]

    def _latest_crystal(self, campaign_id: str, tier: CrystalTier) -> MemoryCrystal | None:
        for crystal in reversed(self._crystals.get(campaign_id, [])):
            if crystal.tier == tier:
                return crystal
        return None

    # ── SHORT crystal creation (from raw events) ────────────────────

    async def crystallize_short(self, campaign_id: str, language: str = "en") -> MemoryCrystal | None:
        """Create a SHORT crystal from recent uncrystallized events."""
        events = self._get_uncrystallized_events(
            campaign_id, limit=self.MAX_CRYSTALLIZE_EVENTS,
        )
        if not events:
            return None

        events_text = self._format_event_batch(events)
        ai_content, player_summary = await self._compress_with_llm(
            tier=CrystalTier.SHORT,
            source_text=events_text,
            max_tokens=2048,
            language=language,
        )
        if not ai_content:
            ai_content = self._fallback_short(events)
        if not player_summary:
            player_summary = self._fallback_player_summary(events)

        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=CrystalTier.SHORT,
            content=player_summary,
            ai_content=ai_content,
            event_count=len(events),
            source_start_created_at=events[0].created_at,
            source_end_created_at=events[-1].created_at,
        )
        self._crystals.setdefault(campaign_id, []).append(crystal)
        self._persist_crystal(campaign_id, crystal)
        self._last_crystal_cursor[campaign_id] = events[-1].created_at
        logger.info(
            "SHORT crystal created: %d events → %d chars ai_content (campaign %s)",
            len(events), len(ai_content), campaign_id,
        )
        return crystal

    # ── Tier consolidation (SHORT→MEDIUM→LONG→MEMORY) ──────────────

    async def _consolidate_tier(
        self, campaign_id: str, target_tier: CrystalTier, language: str = "en",
    ) -> MemoryCrystal | None:
        """Consolidate N crystals of the previous tier into 1 of target_tier."""
        prev_tier = target_tier.previous_tier
        if prev_tier is None:
            return None

        unconsumed = self._unconsumed_crystals(campaign_id, prev_tier)
        if len(unconsumed) < self.CONSOLIDATION_COUNT:
            return None

        # Take the oldest CONSOLIDATION_COUNT unconsumed crystals
        to_merge = unconsumed[:self.CONSOLIDATION_COUNT]
        source_text = "\n---\n".join(c.ai_content for c in to_merge)

        max_tokens = {
            CrystalTier.MEDIUM: 4096,
            CrystalTier.LONG: 8192,
            CrystalTier.MEMORY: 12288,
        }.get(target_tier, 4096)

        ai_content, player_summary = await self._compress_with_llm(
            tier=target_tier,
            source_text=source_text,
            max_tokens=max_tokens,
            language=language,
        )
        if not ai_content:
            # Fallback when LLM consolidation fails: keep all source ai_content
            # blobs verbatim as a JSON array so downstream consumers can still
            # parse / read each one. Lossless beats lossy here.
            ai_content = json.dumps(
                [c.ai_content for c in to_merge], ensure_ascii=False,
            )
        if not player_summary:
            player_summary = " ".join(c.content for c in to_merge)

        total_events = sum(c.event_count for c in to_merge)
        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=target_tier,
            content=player_summary,
            ai_content=ai_content,
            event_count=total_events,
            source_start_created_at=to_merge[0].source_start_created_at,
            source_end_created_at=to_merge[-1].source_end_created_at,
        )
        self._crystals.setdefault(campaign_id, []).append(crystal)
        self._persist_crystal(campaign_id, crystal)

        # Mark source crystals as consumed
        for c in to_merge:
            c.consumed = True

        logger.info(
            "%s crystal created: %d %s crystals → %d chars ai_content (%d total events, campaign %s)",
            target_tier.value, len(to_merge), prev_tier.value,
            len(ai_content), total_events, campaign_id,
        )
        return crystal

    async def cascade_consolidation(self, campaign_id: str, language: str = "en") -> list[MemoryCrystal]:
        """Run the full consolidation cascade: SHORT→MEDIUM→LONG→MEMORY.

        After creating a SHORT crystal, checks if enough unconsumed crystals
        exist at each tier to trigger the next consolidation level.
        Returns all newly created crystals.
        """
        created: list[MemoryCrystal] = []
        for target_tier in (CrystalTier.MEDIUM, CrystalTier.LONG, CrystalTier.MEMORY):
            crystal = await self._consolidate_tier(campaign_id, target_tier, language=language)
            if crystal:
                created.append(crystal)
            else:
                break  # No point checking higher tiers if this one didn't trigger
        return created

    # ── Auto-crystallize (called from game_session) ─────────────────

    async def auto_crystallize_if_needed(self, campaign_id: str, language: str = "en") -> MemoryCrystal | None:
        """Auto-crystallize when raw events exceed threshold, then cascade."""
        if campaign_id in self._crystallizing:
            return None

        pending_events = self._get_uncrystallized_events(
            campaign_id, limit=self.AUTO_CRYSTALLIZE_THRESHOLD + 1,
        )
        if len(pending_events) < self.AUTO_CRYSTALLIZE_THRESHOLD:
            return None

        self._crystallizing.add(campaign_id)
        try:
            logger.info(
                "Auto-crystallizing %d events for campaign %s",
                len(pending_events), campaign_id,
            )
            short_crystal = await self.crystallize_short(campaign_id, language=language)
            if short_crystal:
                # Cascade: check if we can consolidate higher tiers
                cascaded = await self.cascade_consolidation(campaign_id, language=language)
                if cascaded:
                    logger.info(
                        "Cascade created %d higher-tier crystals: %s",
                        len(cascaded),
                        [c.tier.value for c in cascaded],
                    )
            return short_crystal
        except Exception:
            logger.warning("Auto-crystallization failed for campaign %s", campaign_id, exc_info=True)
            return None
        finally:
            self._crystallizing.discard(campaign_id)

    # ── Backward compat: crystallize() delegates to crystallize_short ──

    async def crystallize(
        self,
        campaign_id: str,
        tier: CrystalTier = CrystalTier.SHORT,
        force: bool = False,
        language: str = "en",
    ) -> MemoryCrystal:
        """Backward-compatible crystallize. SHORT → crystallize_short, others → consolidate."""
        if tier == CrystalTier.SHORT:
            result = await self.crystallize_short(campaign_id, language=language)
            if result:
                return result
            # Return latest if nothing new
            latest = self._latest_crystal(campaign_id, CrystalTier.SHORT)
            if latest:
                return latest
            return MemoryCrystal(
                campaign_id=campaign_id, tier=tier,
                content="No events yet.", ai_content="MEM:EMPTY", event_count=0,
            )
        else:
            result = await self._consolidate_tier(campaign_id, tier)
            if result:
                return result
            latest = self._latest_crystal(campaign_id, tier)
            if latest:
                return latest
            return MemoryCrystal(
                campaign_id=campaign_id, tier=tier,
                content="No events yet.", ai_content="MEM:EMPTY", event_count=0,
            )

    # ── LLM compression ────────────────────────────────────────────

    # Soft character limits per tier for ai_content. With structured-JSON
    # crystals on a 1M-context provider these are headroom guardrails, not
    # hard cuts — exceeding them logs a warning but the full JSON is kept,
    # because mid-cutting JSON corrupts the parse downstream.
    _AI_CHAR_LIMITS = {
        CrystalTier.SHORT: 2_000,
        CrystalTier.MEDIUM: 5_000,
        CrystalTier.LONG: 10_000,
        CrystalTier.MEMORY: 20_000,
    }

    async def _compress_with_llm(
        self, tier: CrystalTier, source_text: str, max_tokens: int = 1024,
        language: str = "en",
    ) -> tuple[str, str]:
        """Compress source text using the tier-specific prompt. Returns (ai_content, summary).

        ai_content is a JSON string (the serialized 'ai' object from the LLM response),
        kept verbatim so that downstream consumers (build_context_window, NPC mind,
        consolidation prompts) can re-parse the structured facts.
        """
        prompt_text = _CRYSTAL_PROMPTS.get(tier, _CRYSTAL_PROMPTS[CrystalTier.SHORT])
        if language and language != "en":
            prompt_text += (
                f"\n\nLANGUAGE: Write all string values (descriptions, states, summaries, "
                f"promises, world_facts, summary) in {language}. Proper names stay exactly "
                f"as in the source."
            )
        messages = [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": source_text},
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=max_tokens)
            parsed = parse_json_dict(raw)
            if parsed:
                ai_value = parsed.get("ai", parsed.get("ai_memory", ""))
                if isinstance(ai_value, (dict, list)):
                    ai = json.dumps(ai_value, ensure_ascii=False)
                else:
                    ai = str(ai_value).strip()
                summary = str(parsed.get("summary", parsed.get("player_summary", ""))).strip()
                char_limit = self._AI_CHAR_LIMITS.get(tier, 2_000)
                if len(ai) > char_limit:
                    logger.warning(
                        "Crystal %s ai_content exceeds soft limit (%d > %d) — keeping full content",
                        tier.value, len(ai), char_limit,
                    )
                return ai, summary
        except Exception:
            logger.warning("LLM crystal compression failed for tier %s", tier.value, exc_info=True)
        return "", ""

    # ── Context window builder ──────────────────────────────────────

    def build_context_window(self, campaign_id: str) -> str:
        """Build the WORLD MEMORY section for the narrator's system prompt.

        Pyramid structure — each tier provides progressively broader context:
        - MEMORY: permanent world facts (all)
        - LONG: story arc summaries (unconsumed, up to 3)
        - MEDIUM: consolidated summaries (unconsumed, up to 3)
        - SHORT: recent recaps (unconsumed, up to 3)
        - DELTA: raw uncrystallized events (last few)
        """
        parts: list[str] = []

        # MEMORY tier: permanent facts (show all)
        memory_crystals = [
            c for c in self._crystals.get(campaign_id, [])
            if c.tier == CrystalTier.MEMORY
        ]
        if memory_crystals:
            parts.append("=== PRMNT_MEM ===")
            for c in memory_crystals:
                parts.append(c.ai_content)

        # LONG tier: arc summaries (unconsumed only)
        long_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.LONG)
        if long_crystals:
            parts.append("=== ARC_MEM ===")
            for c in long_crystals[-3:]:
                parts.append(c.ai_content)

        # MEDIUM tier: consolidated (unconsumed only)
        medium_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.MEDIUM)
        if medium_crystals:
            parts.append("=== MID_MEM ===")
            for c in medium_crystals[-3:]:
                parts.append(c.ai_content)

        # SHORT tier: recent recaps (unconsumed only)
        short_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.SHORT)
        if short_crystals:
            parts.append("=== RCNT_MEM ===")
            for c in short_crystals[-3:]:
                parts.append(c.ai_content)

        # Raw uncrystallized events (the freshest context)
        raw_tail = self._get_uncrystallized_events(campaign_id, limit=10)
        if raw_tail:
            parts.append("=== DELTA ===")
            for event in raw_tail:
                compact = self._event_to_compact_line(event)
                if compact:
                    parts.append(compact)

        return "\n".join(parts)

    async def build_context_window_async(self, campaign_id: str) -> str:
        """Async version with optional Graphiti fact retrieval."""
        parts: list[str] = []

        # Same pyramid as sync version
        memory_crystals = [
            c for c in self._crystals.get(campaign_id, [])
            if c.tier == CrystalTier.MEMORY
        ]
        if memory_crystals:
            parts.append("=== PRMNT_MEM ===")
            for c in memory_crystals:
                parts.append(c.ai_content)

        long_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.LONG)
        if long_crystals:
            parts.append("=== ARC_MEM ===")
            for c in long_crystals[-3:]:
                parts.append(c.ai_content)

        medium_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.MEDIUM)
        if medium_crystals:
            parts.append("=== MID_MEM ===")
            for c in medium_crystals[-3:]:
                parts.append(c.ai_content)

        short_crystals = self._unconsumed_crystals(campaign_id, CrystalTier.SHORT)
        if short_crystals:
            parts.append("=== RCNT_MEM ===")
            for c in short_crystals[-3:]:
                parts.append(c.ai_content)

        # Graphiti world facts (if available)
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

        raw_tail = self._get_uncrystallized_events(campaign_id, limit=10)
        if raw_tail:
            parts.append("=== DELTA ===")
            for event in raw_tail:
                compact = self._event_to_compact_line(event)
                if compact:
                    parts.append(compact)

        return "\n".join(parts)

    # ── Persistence ─────────────────────────────────────────────────

    def _persist_crystal(self, campaign_id: str, crystal: MemoryCrystal) -> None:
        try:
            self._store.append(
                campaign_id=campaign_id,
                event_type=EventType.MEMORY_CRYSTAL,
                payload={
                    "tier": crystal.tier.value,
                    "summary": crystal.content,
                    "ai_content": crystal.ai_content,
                    "event_count": crystal.event_count,
                    "consumed": crystal.consumed,
                },
                narrative_time_delta=0,
                location="memory",
                entities=[],
            )
        except Exception:
            logger.warning(
                "Failed to persist %s crystal for campaign %s",
                crystal.tier.value, campaign_id, exc_info=True,
            )

    # ── Event helpers ───────────────────────────────────────────────

    def _get_uncrystallized_events(self, campaign_id: str, limit: int) -> list[Event]:
        cursor = self._last_crystal_cursor.get(campaign_id)
        return self._store.get_after(
            campaign_id=campaign_id,
            after_created_at=cursor,
            limit=limit,
            event_types=list(self.CRYSTALLIZE_EVENT_TYPES),
        )

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

    # ── Fallbacks ───────────────────────────────────────────────────

    def _fallback_short(self, events: list[Event]) -> str:
        """Fallback SHORT crystal when LLM compression fails.

        Produces a minimal structured-JSON entry that matches the crystal
        schema so downstream consumers parse it the same way as a normal
        LLM-generated crystal. No lossy truncation — every unique event
        line survives.
        """
        fallback_events: list[dict] = []
        seen: set[str] = set()
        for event in events:
            line = self._event_to_compact_line(event)
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            fallback_events.append({
                "who": "",
                "action": line,
                "where": getattr(event, "location", "") or "",
                "result": "",
            })
        payload = {
            "events": fallback_events,
            "characters": {},
            "items": [],
            "promises_or_missions": [],
            "world_facts": [],
        }
        return json.dumps(payload, ensure_ascii=False)

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
