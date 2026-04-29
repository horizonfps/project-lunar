from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum

from app.db.event_store import EventStore, Event, EventType
from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


# ── Stop words for keyword extraction (EN + PT) ─────────────────────
# Mirrors the set used in game_session._extract_context_keywords so that
# crystal scoring stays consistent with story-card scoring.
_STOP_WORDS: set[str] = {
    "the", "and", "for", "that", "this", "with", "you", "your", "are",
    "was", "were", "has", "have", "had", "been", "will", "not", "but",
    "from", "they", "she", "his", "her", "its", "our", "que", "para",
    "com", "uma", "por", "ele", "ela", "seu", "sua", "dos", "das",
    "nos", "nas", "mais", "como", "não", "está", "isso", "esse",
    "essa", "são", "tem", "foi", "ser", "ter", "mas", "quando",
    "sobre", "entre", "depois", "antes", "muito", "pode", "seus",
    "suas", "ainda", "também", "apenas", "cada", "outro", "outra",
}


def _extract_keywords(text: str) -> set[str]:
    """Lowercase non-stop tokens of length >=3 from arbitrary text."""
    if not text:
        return set()
    words = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _rag_crystals_enabled() -> bool:
    """Feature flag — defaults ON. Set LUNAR_FEATURE_RAG_CRYSTALS=0/false to disable."""
    raw = os.environ.get("LUNAR_FEATURE_RAG_CRYSTALS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def estimate_tokens_for_crystal(crystal: "MemoryCrystal") -> int:
    """Rough token estimate for a crystal's ai_content payload (~4 chars/token)."""
    text = crystal.ai_content or ""
    return max(1, len(text) // 4)


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
    # Camada 3 — perspective filter. Union of NPC names that witnessed any of
    # the source events / source crystals. MEMORY tier ignores this list
    # (canonical world facts are accessible to every NPC).
    witnessed_by: list[str] = field(default_factory=list)


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

        # Union of every NPC that witnessed any source event. Order doesn't
        # matter — readers will treat this as a set. Player presence is
        # implicit and never recorded.
        witnessed_by_union: list[str] = []
        seen_witnesses: set[str] = set()
        for ev in events:
            for name in (ev.witnessed_by or []):
                key = name.strip().lower()
                if key and key not in seen_witnesses:
                    seen_witnesses.add(key)
                    witnessed_by_union.append(name.strip())

        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=CrystalTier.SHORT,
            content=player_summary,
            ai_content=ai_content,
            event_count=len(events),
            source_start_created_at=events[0].created_at,
            source_end_created_at=events[-1].created_at,
            witnessed_by=witnessed_by_union,
        )
        self._crystals.setdefault(campaign_id, []).append(crystal)
        self._persist_crystal(campaign_id, crystal)
        self._last_crystal_cursor[campaign_id] = events[-1].created_at
        logger.info(
            "SHORT crystal created: %d events → %d chars ai_content "
            "(campaign %s, witnesses=%s)",
            len(events), len(ai_content), campaign_id, witnessed_by_union,
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

        # Union of witnesses from source crystals — broader scope at higher
        # tiers (more NPCs will have witnessed the union of all those scenes),
        # but the perspective filter is still useful: a tier-LONG arc summary
        # of the player's solo journey through a forest legitimately has 0
        # witnesses, and no NPC should learn its contents.
        witnessed_by_union: list[str] = []
        seen_witnesses: set[str] = set()
        for c in to_merge:
            for name in (c.witnessed_by or []):
                key = name.strip().lower()
                if key and key not in seen_witnesses:
                    seen_witnesses.add(key)
                    witnessed_by_union.append(name.strip())

        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=target_tier,
            content=player_summary,
            ai_content=ai_content,
            event_count=total_events,
            source_start_created_at=to_merge[0].source_start_created_at,
            source_end_created_at=to_merge[-1].source_end_created_at,
            witnessed_by=witnessed_by_union,
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

    # ── Crystal scoring (RAG) ──────────────────────────────────────
    # Bonus weights mirror the story-card RAG in game_session so that
    # both retrieval layers rank facts the same way.
    _ACTIVE_NPC_BONUS = 50      # crystal mentions an NPC currently in scene
    _LOCATION_BONUS = 30        # crystal mentions current location
    _KEYWORD_MATCH_SCORE = 5    # per query-keyword hit in ai_content
    _RECENCY_BONUS_MAX = 10     # newest unconsumed crystal of its tier gets this

    # Tier base scores: higher tier means broader (and usually older) context,
    # so without query signal we still bias toward recent/specific tiers but
    # never let a tier dominate purely by being old. These are tiebreakers.
    _TIER_BASE_SCORE = {
        CrystalTier.SHORT: 4.0,
        CrystalTier.MEDIUM: 3.0,
        CrystalTier.LONG: 2.0,
    }

    def _score_crystal(
        self,
        crystal: MemoryCrystal,
        rank_within_tier: int,
        tier_size: int,
        query_keywords: set[str],
        active_npc_names: set[str],
        location_keywords: set[str],
    ) -> float:
        """Score a crystal's relevance to the current scene.

        Score combines:
        - Keyword overlap between query and crystal ai_content (weight 5/hit).
        - Active NPC names appearing in the crystal (weight 50/match).
        - Location keywords appearing in the crystal (weight 30/match).
        - Recency within tier: most-recent crystal of its tier gets a small
          bonus, decaying linearly toward 0 for the oldest in that tier.
        - Tier base: small constant per tier as a tiebreaker.

        MEMORY tier crystals are NEVER scored — they are always included in
        full as canonical world facts. This method is only called for
        SHORT/MEDIUM/LONG.
        """
        ai = (crystal.ai_content or "").lower()
        if not ai:
            return 0.0

        score = self._TIER_BASE_SCORE.get(crystal.tier, 0.0)

        # Keyword overlap. We tokenize the crystal's ai_content the same way
        # the query is tokenized so that quoted JSON keys ("characters",
        # "events", etc.) become noise-immune via the stop list.
        if query_keywords:
            crystal_words = set(re.findall(r"[a-zA-ZÀ-ÿ]{3,}", ai))
            hits = len(query_keywords & crystal_words)
            score += hits * self._KEYWORD_MATCH_SCORE

        # Active NPC presence: substring match (NPC names can be multi-word).
        if active_npc_names:
            for name in active_npc_names:
                name = name.strip().lower()
                if name and name in ai:
                    score += self._ACTIVE_NPC_BONUS

        # Location overlap.
        if location_keywords:
            for loc in location_keywords:
                loc = loc.strip().lower()
                if loc and loc in ai:
                    score += self._LOCATION_BONUS

        # Recency within tier: linearly decay from RECENCY_BONUS_MAX (newest)
        # to 0 (oldest). rank_within_tier is 0-based from oldest → newest.
        if tier_size > 1:
            recency = (rank_within_tier / (tier_size - 1)) * self._RECENCY_BONUS_MAX
        else:
            recency = self._RECENCY_BONUS_MAX
        score += recency

        return score

    # ── Context window budget ──────────────────────────────────────
    # Allocate ~10% of provider context window to crystal recall (separate
    # from story cards' 15%). Floor / ceiling keep behavior sane on small
    # providers and prevent runaway on 1M-token windows.
    _CRYSTALS_CONTEXT_FRACTION = 0.10
    _CRYSTALS_MIN_BUDGET_TOKENS = 4_000
    _CRYSTALS_MAX_BUDGET_TOKENS = 100_000

    def _compute_crystals_budget(self, context_window: int) -> int:
        if context_window <= 0:
            return self._CRYSTALS_MIN_BUDGET_TOKENS
        budget = int(context_window * self._CRYSTALS_CONTEXT_FRACTION)
        return max(
            self._CRYSTALS_MIN_BUDGET_TOKENS,
            min(self._CRYSTALS_MAX_BUDGET_TOKENS, budget),
        )

    def _select_ranked_crystals(
        self,
        campaign_id: str,
        tier: CrystalTier,
        query_keywords: set[str],
        active_npc_names: set[str],
        location_keywords: set[str],
        token_budget: int,
    ) -> list[MemoryCrystal]:
        """Score unconsumed crystals of `tier` and return top-N within budget.

        Crystals are ranked by `_score_crystal`, then included greedily until
        the per-tier token budget runs out. Ordering of the returned list is
        chronological (oldest → newest) so the narrator sees the natural arc.
        """
        unconsumed = self._unconsumed_crystals(campaign_id, tier)
        if not unconsumed:
            return []

        tier_size = len(unconsumed)
        scored: list[tuple[float, int, MemoryCrystal]] = []
        for rank, crystal in enumerate(unconsumed):
            score = self._score_crystal(
                crystal=crystal,
                rank_within_tier=rank,
                tier_size=tier_size,
                query_keywords=query_keywords,
                active_npc_names=active_npc_names,
                location_keywords=location_keywords,
            )
            scored.append((score, rank, crystal))

        # Highest score first; ties broken by recency (higher rank = newer).
        scored.sort(key=lambda x: (-x[0], -x[1]))

        selected: list[tuple[int, MemoryCrystal]] = []
        used_tokens = 0
        for score, rank, crystal in scored:
            cost = estimate_tokens_for_crystal(crystal)
            if used_tokens + cost > token_budget and selected:
                break
            selected.append((rank, crystal))
            used_tokens += cost

        # Restore chronological order for narrator readability.
        selected.sort(key=lambda x: x[0])
        return [c for _, c in selected]

    # ── Context window builder ──────────────────────────────────────

    def build_context_window(
        self,
        campaign_id: str,
        query_text: str = "",
        active_npc_names: set[str] | None = None,
        location: str = "",
        context_window: int = 0,
    ) -> str:
        """Build the WORLD MEMORY section for the narrator's system prompt.

        Pyramid structure — each tier provides progressively broader context:
        - MEMORY: permanent world facts (all — canonical, never filtered).
        - LONG / MEDIUM / SHORT: ranked by relevance to (query, NPCs, location)
          when those are provided AND the RAG flag is on. Otherwise falls back
          to the legacy "last 3 unconsumed" behavior (preserves old tests and
          callers that don't have query context, e.g. routes_game generation).
        - DELTA: raw uncrystallized events (last few).
        """
        parts: list[str] = []

        rag_on = _rag_crystals_enabled() and bool(
            query_text or active_npc_names or location
        )
        active_npc_names = {n.lower() for n in (active_npc_names or set()) if n}
        query_keywords = _extract_keywords(query_text)
        location_keywords = _extract_keywords(location)

        # MEMORY tier: permanent facts (show all)
        memory_crystals = [
            c for c in self._crystals.get(campaign_id, [])
            if c.tier == CrystalTier.MEMORY
        ]
        if memory_crystals:
            parts.append("=== PRMNT_MEM ===")
            for c in memory_crystals:
                parts.append(c.ai_content)

        if rag_on:
            tier_budget = self._compute_crystals_budget(context_window) // 3
            for tier, header in (
                (CrystalTier.LONG, "=== ARC_MEM ==="),
                (CrystalTier.MEDIUM, "=== MID_MEM ==="),
                (CrystalTier.SHORT, "=== RCNT_MEM ==="),
            ):
                ranked = self._select_ranked_crystals(
                    campaign_id, tier,
                    query_keywords=query_keywords,
                    active_npc_names=active_npc_names,
                    location_keywords=location_keywords,
                    token_budget=tier_budget,
                )
                if ranked:
                    parts.append(header)
                    for c in ranked:
                        parts.append(c.ai_content)
        else:
            for tier, header in (
                (CrystalTier.LONG, "=== ARC_MEM ==="),
                (CrystalTier.MEDIUM, "=== MID_MEM ==="),
                (CrystalTier.SHORT, "=== RCNT_MEM ==="),
            ):
                tier_crystals = self._unconsumed_crystals(campaign_id, tier)
                if tier_crystals:
                    parts.append(header)
                    for c in tier_crystals[-3:]:
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

    async def build_context_window_async(
        self,
        campaign_id: str,
        query_text: str = "",
        active_npc_names: set[str] | None = None,
        location: str = "",
        context_window: int = 0,
    ) -> str:
        """Async version with optional Graphiti fact retrieval. Same RAG semantics."""
        parts: list[str] = []

        rag_on = _rag_crystals_enabled() and bool(
            query_text or active_npc_names or location
        )
        active_npc_names = {n.lower() for n in (active_npc_names or set()) if n}
        query_keywords = _extract_keywords(query_text)
        location_keywords = _extract_keywords(location)

        memory_crystals = [
            c for c in self._crystals.get(campaign_id, [])
            if c.tier == CrystalTier.MEMORY
        ]
        if memory_crystals:
            parts.append("=== PRMNT_MEM ===")
            for c in memory_crystals:
                parts.append(c.ai_content)

        if rag_on:
            tier_budget = self._compute_crystals_budget(context_window) // 3
            for tier, header in (
                (CrystalTier.LONG, "=== ARC_MEM ==="),
                (CrystalTier.MEDIUM, "=== MID_MEM ==="),
                (CrystalTier.SHORT, "=== RCNT_MEM ==="),
            ):
                ranked = self._select_ranked_crystals(
                    campaign_id, tier,
                    query_keywords=query_keywords,
                    active_npc_names=active_npc_names,
                    location_keywords=location_keywords,
                    token_budget=tier_budget,
                )
                if ranked:
                    parts.append(header)
                    for c in ranked:
                        parts.append(c.ai_content)
        else:
            for tier, header in (
                (CrystalTier.LONG, "=== ARC_MEM ==="),
                (CrystalTier.MEDIUM, "=== MID_MEM ==="),
                (CrystalTier.SHORT, "=== RCNT_MEM ==="),
            ):
                tier_crystals = self._unconsumed_crystals(campaign_id, tier)
                if tier_crystals:
                    parts.append(header)
                    for c in tier_crystals[-3:]:
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

    # ── NPC perspective filter (Camada 3) ──────────────────────────

    def build_npc_knowledge_window(
        self,
        campaign_id: str,
        npc_name: str,
    ) -> str:
        """Return the subset of WORLD MEMORY this NPC could plausibly know.

        Rules:
        - MEMORY tier crystals are ALWAYS included (canonical world facts —
          public lore that everyone in the world treats as true).
        - LONG / MEDIUM / SHORT crystals are included only if `npc_name`
          appears in their `witnessed_by` list.
        - Raw uncrystallized events are included only if the NPC is in the
          event's `witnessed_by` list.

        Empty string when nothing is accessible. Used by the narrator-prompt
        NPC KNOWLEDGE BOUNDARIES block and by `update_npc_thoughts` so that
        each NPC's reasoning stays consistent with what they could have seen.
        """
        if not npc_name:
            return ""
        name_key = npc_name.strip().lower()
        crystals = self._crystals.get(campaign_id, [])

        parts: list[str] = []

        # MEMORY tier — always canon, never filtered.
        memory_crystals = [c for c in crystals if c.tier == CrystalTier.MEMORY]
        if memory_crystals:
            parts.append("=== PRMNT_MEM (canon — known to everyone) ===")
            for c in memory_crystals:
                parts.append(c.ai_content)

        # LONG/MEDIUM/SHORT — only those this NPC witnessed.
        for tier, header in (
            (CrystalTier.LONG, "=== ARC_MEM (witnessed) ==="),
            (CrystalTier.MEDIUM, "=== MID_MEM (witnessed) ==="),
            (CrystalTier.SHORT, "=== RCNT_MEM (witnessed) ==="),
        ):
            tier_crystals = [
                c for c in crystals
                if c.tier == tier
                and not c.consumed
                and any(w.strip().lower() == name_key for w in (c.witnessed_by or []))
            ]
            if tier_crystals:
                parts.append(header)
                for c in tier_crystals:
                    parts.append(c.ai_content)

        # Raw uncrystallized events — only those this NPC witnessed.
        raw_tail = self._get_uncrystallized_events(campaign_id, limit=20)
        witnessed_raw = [
            ev for ev in raw_tail
            if any(w.strip().lower() == name_key for w in (ev.witnessed_by or []))
        ]
        if witnessed_raw:
            parts.append("=== DELTA (witnessed) ===")
            for event in witnessed_raw:
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
                    "witnessed_by": list(crystal.witnessed_by or []),
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
