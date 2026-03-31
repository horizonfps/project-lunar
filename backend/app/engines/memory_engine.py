from __future__ import annotations
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
# Each tier gets progressively more compressed.
# The style: remove vowels, abbreviate, telegraph-style — just enough
# for an LLM to reconstruct meaning.

_CRYSTAL_PROMPTS = {
    CrystalTier.SHORT: (
        "You are a memory compressor for an RPG AI engine.\n"
        "Return ONLY valid JSON (no markdown): {\"ai\": str, \"summary\": str}\n\n"
        "CRITICAL: The 'ai' field MUST be under 200 characters. This is a HARD LIMIT.\n"
        "Going over 200 characters is a FAILURE. Count carefully.\n\n"
        "COMPRESSION STYLE for 'ai':\n"
        "- Rmv vwls frm cmmn wrds (kp prpr nms rdbl)\n"
        "- Abbrvtns: plyr=player, cmbt=combat, mv=move, mt=meet, dscvr=discover, dfnd=defend\n"
        "- Symbols: →=goes to, +=gains, -=loses, ⚔=combat, ✓=success, ✗=fail, @=name\n"
        "- Pipes | to separate facts\n"
        "- ONLY: names, locations, items, decisions, combat results\n"
        "- DROP: descriptions, atmosphere, movement details, dialogue\n\n"
        "EXAMPLES:\n"
        "- \"@Yuuta dscvr bsmnt acdmy→fnd crystl cmpss|@Orla frwll clsd|snsr mp cmplt\"\n"
        "- \"@Kael ⚔ @Yuuta ✗ FAIL|plyr -HP, lstpstns|@Selene obsrvs frm dstns\"\n"
        "- \"plyr mt @Voss, by prsnc sprssn|mv→grdns|dfrrd artfct rtrval\"\n\n"
        "- 'summary': 1 short sentence for player UI (human-readable, normal language)."
    ),
    CrystalTier.MEDIUM: (
        "You are a memory compressor for an RPG AI engine.\n"
        "Consolidate these SHORT crystal memories into a MEDIUM-level summary.\n"
        "Return ONLY valid JSON (no markdown): {\"ai\": str, \"summary\": str}\n\n"
        "COMPRESSION RULES for 'ai' field:\n"
        "- Merge overlapping facts, drop redundancies\n"
        "- Keep the SAME compressed style (no vowels, abbreviations, symbols)\n"
        "- Focus on: relationships formed, items gained/lost, locations discovered, "
        "combat outcomes, promises made, power changes\n"
        "- MAX 300 characters for 'ai' field\n"
        "- Structure: REL:[relationships] EVT:[key events] ITM:[items] LOC:[locations]\n\n"
        "- 'summary' field: 2-3 normal sentences for player UI."
    ),
    CrystalTier.LONG: (
        "You are a memory compressor for an RPG AI engine.\n"
        "Consolidate these MEDIUM crystal memories into a LONG-level arc summary.\n"
        "Return ONLY valid JSON (no markdown): {\"ai\": str, \"summary\": str}\n\n"
        "COMPRESSION RULES for 'ai' field:\n"
        "- This covers a MAJOR story arc (dozens of actions)\n"
        "- Extract only: permanent relationships, major plot points, lasting world changes, "
        "player power level shifts, faction standings\n"
        "- Same compressed style but even more selective\n"
        "- MAX 400 characters for 'ai' field\n"
        "- Structure: ARC:[story arc summary] REL:[permanent relationships] WRLD:[world state]\n\n"
        "- 'summary' field: 3-4 normal sentences for player UI."
    ),
    CrystalTier.MEMORY: (
        "You are a memory compressor for an RPG AI engine.\n"
        "Consolidate these LONG crystal memories into PERMANENT world facts.\n"
        "Return ONLY valid JSON (no markdown): {\"ai\": str, \"summary\": str}\n\n"
        "COMPRESSION RULES for 'ai' field:\n"
        "- PERMANENT FACTS ONLY — things that will NEVER change or are critical backstory\n"
        "- Who the player IS, their origin, core abilities, permanent allies/enemies\n"
        "- Major completed arcs (resolved, no need for detail)\n"
        "- World-altering events that define the current state\n"
        "- MAX 500 characters for 'ai' field\n"
        "- Structure: ID:[player identity] HIST:[completed arcs] WRLD:[permanent world state]\n\n"
        "- 'summary' field: 4-5 normal sentences for player UI — full story recap."
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

    async def crystallize_short(self, campaign_id: str) -> MemoryCrystal | None:
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
            max_tokens=256,
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
        self, campaign_id: str, target_tier: CrystalTier,
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
            CrystalTier.MEDIUM: 768,
            CrystalTier.LONG: 1024,
            CrystalTier.MEMORY: 1280,
        }.get(target_tier, 1024)

        ai_content, player_summary = await self._compress_with_llm(
            tier=target_tier,
            source_text=source_text,
            max_tokens=max_tokens,
        )
        if not ai_content:
            # Fallback: just concatenate with separator
            ai_content = " | ".join(c.ai_content for c in to_merge)
            if len(ai_content) > 500:
                ai_content = ai_content[:497] + "..."
        if not player_summary:
            player_summary = " ".join(c.content for c in to_merge)
            if len(player_summary) > 600:
                player_summary = player_summary[:597] + "..."

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

    async def cascade_consolidation(self, campaign_id: str) -> list[MemoryCrystal]:
        """Run the full consolidation cascade: SHORT→MEDIUM→LONG→MEMORY.

        After creating a SHORT crystal, checks if enough unconsumed crystals
        exist at each tier to trigger the next consolidation level.
        Returns all newly created crystals.
        """
        created: list[MemoryCrystal] = []
        for target_tier in (CrystalTier.MEDIUM, CrystalTier.LONG, CrystalTier.MEMORY):
            crystal = await self._consolidate_tier(campaign_id, target_tier)
            if crystal:
                created.append(crystal)
            else:
                break  # No point checking higher tiers if this one didn't trigger
        return created

    # ── Auto-crystallize (called from game_session) ─────────────────

    async def auto_crystallize_if_needed(self, campaign_id: str) -> MemoryCrystal | None:
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
            short_crystal = await self.crystallize_short(campaign_id)
            if short_crystal:
                # Cascade: check if we can consolidate higher tiers
                cascaded = await self.cascade_consolidation(campaign_id)
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
    ) -> MemoryCrystal:
        """Backward-compatible crystallize. SHORT → crystallize_short, others → consolidate."""
        if tier == CrystalTier.SHORT:
            result = await self.crystallize_short(campaign_id)
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

    # Hard character limits per tier for ai_content (enforced post-LLM)
    _AI_CHAR_LIMITS = {
        CrystalTier.SHORT: 250,
        CrystalTier.MEDIUM: 400,
        CrystalTier.LONG: 500,
        CrystalTier.MEMORY: 600,
    }

    async def _compress_with_llm(
        self, tier: CrystalTier, source_text: str, max_tokens: int = 512,
    ) -> tuple[str, str]:
        """Compress source text using the tier-specific prompt. Returns (ai_content, summary)."""
        prompt_text = _CRYSTAL_PROMPTS.get(tier, _CRYSTAL_PROMPTS[CrystalTier.SHORT])
        messages = [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": source_text},
        ]
        try:
            raw = await self._llm.complete(messages=messages, max_tokens=max_tokens)
            parsed = parse_json_dict(raw)
            if parsed:
                ai = str(parsed.get("ai", parsed.get("ai_memory", ""))).strip()
                summary = str(parsed.get("summary", parsed.get("player_summary", ""))).strip()
                # Hard truncation — LLMs often exceed char limits
                char_limit = self._AI_CHAR_LIMITS.get(tier, 300)
                if len(ai) > char_limit:
                    logger.warning(
                        "Crystal %s ai_content too long (%d > %d), truncating",
                        tier.value, len(ai), char_limit,
                    )
                    ai = ai[:char_limit].rsplit("|", 1)[0]  # cut at last pipe
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
        """Fallback SHORT crystal when LLM fails — compact pipe-separated."""
        compact_lines: list[str] = []
        seen: set[str] = set()
        for event in events[-8:]:
            line = self._event_to_compact_line(event)
            if not line:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            compact_lines.append(line)
        result = "|".join(compact_lines)
        if len(result) > 300:
            result = result[-300:]
        return result or "MEM:EMPTY"

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
