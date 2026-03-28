from __future__ import annotations
import json
import logging
from dataclasses import asdict
from typing import AsyncIterator

from app.db.event_store import EventStore, EventType
from app.engines.llm_router import LLMProvider
from app.engines.narrator_engine import NarrativeMode, estimate_tokens
from app.engines.plot_generator import AUTO_PLOT_RULES
from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


class GameSession:
    def __init__(
        self,
        campaign_id: str,
        scenario_tone: str,
        language: str,
        narrator,
        memory,
        world_reactor,
        journal,
        event_store: EventStore,
        combat_engine=None,
        graph_engine=None,
        npc_minds=None,
        graphiti_engine=None,
        plot_generator=None,
        inventory_engine=None,
        auto_plot_rules=None,
        opening_narrative: str = "",
        story_cards: list | None = None,
    ):
        self.campaign_id = campaign_id
        self.scenario_tone = scenario_tone
        self.language = language
        self._narrator = narrator
        self._memory = memory
        self._story_cards = story_cards or []
        self._world_reactor = world_reactor
        self._journal = journal
        self._event_store = event_store
        self._combat = combat_engine
        self._graph = graph_engine
        self._npc_minds = npc_minds
        self._graphiti = graphiti_engine
        self._plot_generator = plot_generator
        self._inventory = inventory_engine
        self._history: list[dict] = []
        self._turn_count = 0
        self._auto_plot_rules = auto_plot_rules or AUTO_PLOT_RULES
        self._auto_plot_state: dict[str, dict[str, int]] = {
            kind: {"last_turn": 0, "last_narrative_time": 0, "trigger_count": 0}
            for kind in self._auto_plot_rules.keys()
        }
        # Active plot seeds and micro-hooks fed to the narrator as context
        self._active_plot_seeds: list[str] = []
        self._pending_micro_hook: str = ""
        # Pending NPC seed: an auto-generated NPC waiting to be introduced
        # in the narrative. Only one at a time — no new generation until
        # the narrator has woven this NPC into the story.
        self._pending_npc_seed: dict | None = None
        self._pending_npc_introduced = False
        # Plot lock: only one active element at a time. A new element can only
        # be generated after the current one is presented and developed.
        self._plot_pending = False
        self._plot_pending_since_turn = 0
        self._PLOT_CONSUME_TURNS = 4  # minimum turns before a plot is considered consumed
        self._PLOT_MIN_CONSUME_TURNS = 2  # minimum turns even if confirmed in narrative

        # Player power level (0-10), initialized from scenario or events
        self._player_power: int = self._init_player_power()

        # Rebuild conversation history from persisted events so the AI
        # has full context even after a server restart or new session.
        self._rebuild_history_from_events()
        self._rebuild_npc_minds_from_events()
        self._rebuild_plot_lock_from_events()
        self._rebuild_journal_from_events()
        self._rebuild_memory_crystals()
        self._rebuild_player_power()

        # If this is a brand-new campaign (no history) and we have an
        # opening narrative, seed the history so the AI knows the story setup.
        if not self._history and opening_narrative:
            self._history.append({"role": "assistant", "content": opening_narrative})

    def _rebuild_history_from_events(self) -> None:
        """Rebuild _history from persisted events so the AI retains context."""
        player_events = self._event_store.get_by_type(
            self.campaign_id, EventType.PLAYER_ACTION,
        )
        narrator_events = self._event_store.get_by_type(
            self.campaign_id, EventType.NARRATOR_RESPONSE,
        )
        all_events = player_events + narrator_events
        all_events.sort(key=lambda e: e.created_at)
        for ev in all_events:
            text = ev.payload.get("text", "")
            if not text:
                continue
            if ev.event_type == EventType.PLAYER_ACTION:
                self._history.append({"role": "user", "content": text})
            else:
                self._history.append({"role": "assistant", "content": text})
        self._turn_count = len(player_events)

    def _rebuild_npc_minds_from_events(self) -> None:
        """Rebuild NPC minds from persisted NPC_THOUGHT events."""
        if not self._npc_minds:
            return
        thought_events = self._event_store.get_by_type(
            self.campaign_id, EventType.NPC_THOUGHT,
        )
        if not thought_events:
            return
        # Group by NPC name, keeping the latest thoughts per NPC
        latest_per_npc: dict[str, dict] = {}
        for ev in thought_events:
            name = ev.payload.get("name", "")
            if name:
                latest_per_npc[name] = ev.payload
        # Reconstruct minds
        for name, payload in latest_per_npc.items():
            mind = self._npc_minds._ensure_mind(self.campaign_id, name)
            for alias in payload.get("aliases", []):
                if alias.lower() not in [a.lower() for a in mind.aliases]:
                    mind.aliases.append(alias)
            for key, value in payload.get("thoughts", {}).items():
                if value:
                    mind.set_thought(key, str(value))
        logger.info(
            "Rebuilt %d NPC minds from events for campaign %s",
            len(latest_per_npc), self.campaign_id,
        )

    def _rebuild_plot_lock_from_events(self) -> None:
        """Rebuild plot seeds, NPC seeds, micro-hooks, auto-plot counters,
        and lock from persisted PLOT_GENERATION events."""
        plot_events = self._event_store.get_by_type(
            self.campaign_id, EventType.PLOT_GENERATION,
        )
        if not plot_events:
            return

        player_events = self._event_store.get_by_type(
            self.campaign_id, EventType.PLAYER_ACTION,
        )

        # Rebuild active plot seeds, micro-hooks, and auto_plot_state counters
        for ev in plot_events:
            kind = ev.payload.get("kind", "")
            if kind == "plot_arc":
                text = ev.payload.get("data", {}).get("text", "")
                if text:
                    self._active_plot_seeds.append(text)
            elif kind == "micro_hook":
                text = ev.payload.get("data", {}).get("text", "")
                if text:
                    # Check if any narrator response after this event consumed it
                    narrator_events = self._event_store.get_by_type(
                        self.campaign_id, EventType.NARRATOR_RESPONSE,
                    )
                    consumed = any(
                        e.created_at > ev.created_at for e in narrator_events
                    )
                    if not consumed:
                        self._pending_micro_hook = text

            # Rebuild auto_plot_state counters per kind
            if kind in self._auto_plot_state:
                state = self._auto_plot_state[kind]
                state["trigger_count"] += 1
                # Derive last_turn: count player actions up to this event
                turns_at_event = sum(
                    1 for e in player_events if e.created_at <= ev.created_at
                )
                state["last_turn"] = turns_at_event

        # Restore pending NPC seed if the last plot event was an NPC
        # and it hasn't been introduced yet (name not found in subsequent narratives)
        last_plot = plot_events[-1]
        last_kind = last_plot.payload.get("kind", "")
        if last_kind == "npc":
            npc_data = last_plot.payload.get("data", {})
            npc_name = npc_data.get("name", "")
            if npc_name:
                narrator_events = self._event_store.get_by_type(
                    self.campaign_id, EventType.NARRATOR_RESPONSE,
                )
                introduced = any(
                    npc_name.lower() in (e.payload.get("text", "") or "").lower()
                    for e in narrator_events
                    if e.created_at > last_plot.created_at
                )
                if not introduced:
                    self._pending_npc_seed = npc_data
                    self._pending_npc_introduced = False
                    logger.info(
                        "Restored pending NPC seed '%s' from events for campaign %s",
                        npc_name, self.campaign_id,
                    )
                else:
                    self._pending_npc_introduced = True

        # Check lock: count player actions after the last plot
        turns_after_plot = sum(
            1 for e in player_events if e.created_at > last_plot.created_at
        )
        if turns_after_plot < self._PLOT_CONSUME_TURNS:
            self._plot_pending = True
            self._plot_pending_since_turn = self._turn_count - turns_after_plot

    def rewind(self) -> None:
        """Fully rewind the last action: rebuild all in-memory state from events.

        After the route handler deletes the last event pair from the store,
        this method reconstructs history, NPC minds, journal, plot state,
        and memory crystals from the remaining events so that the game
        state is fully consistent.
        """
        # Reset all in-memory state
        self._history.clear()
        self._turn_count = 0
        if self._npc_minds:
            self._npc_minds._minds.pop(self.campaign_id, None)
        self._active_plot_seeds.clear()
        self._pending_micro_hook = ""
        self._pending_npc_seed = None
        self._pending_npc_introduced = False
        self._plot_pending = False
        self._plot_pending_since_turn = 0
        for state in self._auto_plot_state.values():
            state["last_turn"] = 0
            state["last_narrative_time"] = 0
            state["trigger_count"] = 0

        # Rebuild from remaining events
        self._rebuild_history_from_events()
        self._rebuild_npc_minds_from_events()
        self._rebuild_plot_lock_from_events()
        self._rebuild_journal_from_events()
        self._rebuild_memory_crystals()

    def _rebuild_journal_from_events(self) -> None:
        """Rebuild the journal in-memory state from JOURNAL_ENTRY events in the store."""
        if not self._journal:
            return
        # Clear existing journal for this campaign
        self._journal._journals.pop(self.campaign_id, None)
        # Rebuild from persisted JOURNAL_ENTRY events
        from app.engines.journal_engine import JournalEntry, JournalCategory
        journal_events = self._event_store.get_by_type(
            self.campaign_id, EventType.JOURNAL_ENTRY,
        )
        if not journal_events:
            return
        entries = []
        for ev in journal_events:
            try:
                category = JournalCategory(ev.payload.get("category", ""))
                entries.append(JournalEntry(
                    campaign_id=self.campaign_id,
                    category=category,
                    summary=ev.payload.get("summary", ""),
                    created_at=ev.created_at,
                ))
            except (ValueError, KeyError):
                continue
        if entries:
            self._journal._journals[self.campaign_id] = entries
        logger.info(
            "Rebuilt %d journal entries from events for campaign %s",
            len(entries), self.campaign_id,
        )

    def _rebuild_memory_crystals(self) -> None:
        """Rebuild memory crystals from MEMORY_CRYSTAL events in the store."""
        from app.engines.memory_engine import MemoryCrystal, CrystalTier
        crystal_events = self._event_store.get_by_type(
            self.campaign_id, EventType.MEMORY_CRYSTAL,
        )
        crystals = []
        for ev in crystal_events:
            try:
                tier = CrystalTier(ev.payload.get("tier", "SHORT"))
                crystals.append(MemoryCrystal(
                    campaign_id=self.campaign_id,
                    tier=tier,
                    content=ev.payload.get("summary", ""),
                    ai_content=ev.payload.get("ai_content", ""),
                    event_count=ev.payload.get("event_count", 0),
                    source_start_created_at=None,
                    source_end_created_at=ev.created_at,
                ))
            except Exception:
                continue
        self._memory._crystals[self.campaign_id] = crystals
        # Reset crystal cursor to last crystal's timestamp
        if crystals:
            self._memory._last_crystal_cursor[self.campaign_id] = crystals[-1].source_end_created_at
        else:
            self._memory._last_crystal_cursor.pop(self.campaign_id, None)

    def _build_power_scale_reference(self) -> str:
        """Build a power scale reference from NPC story cards.

        Uses the existing NPC power_level values as calibration anchors.
        No hardcoded progression system — the scale comes entirely from the scenario data.
        """
        npc_powers = []
        for card in self._story_cards:
            if hasattr(card, 'card_type') and str(card.card_type).upper() == "NPC":
                content = card.content if isinstance(card.content, dict) else {}
                power = content.get("power_level")
                if power is not None:
                    npc_powers.append((card.name, int(power)))
        if not npc_powers:
            return ""
        npc_powers.sort(key=lambda x: x[1], reverse=True)
        # Include both ends of the scale — top AND bottom anchors
        # so the LLM sees what "strong" and "weak" look like in this world.
        if len(npc_powers) <= 20:
            selected = npc_powers
        else:
            top = npc_powers[:12]
            bottom = npc_powers[-8:]
            # Deduplicate in case of overlap
            seen = {n for n, _ in top}
            for item in bottom:
                if item[0] not in seen:
                    top.append(item)
                    seen.add(item[0])
            selected = sorted(top, key=lambda x: x[1], reverse=True)
        lines = [f"  {name}: {p}/10" for name, p in selected]
        return (
            "WORLD POWER SCALE — use these characters as anchors when estimating power:\n"
            + "\n".join(lines)
            + "\n"
            "Unnamed creatures/enemies should be calibrated relative to these anchors."
        )

    def _init_player_power(self) -> int:
        """Default player power — will be overridden by LLM evaluation on first action
        or by _rebuild_player_power from events."""
        return 3

    def _rebuild_player_power(self) -> None:
        """Rebuild player power from the latest POWER_LEVEL_UPDATE event."""
        events = self._event_store.get_by_type(
            self.campaign_id, EventType.POWER_LEVEL_UPDATE,
        )
        if events:
            latest = events[-1]
            target = latest.payload.get("target", "")
            if target == "player":
                try:
                    self._player_power = max(0, min(10, int(latest.payload.get("new_power", self._player_power))))
                except (TypeError, ValueError):
                    pass

    def _resolve_opponent_power(self, opponent_name: str, llm_estimate: int) -> int:
        """Resolve opponent power: check story cards first, fall back to LLM estimate."""
        if not opponent_name:
            return llm_estimate

        name_lower = opponent_name.lower()
        for card in self._story_cards:
            if hasattr(card, 'card_type') and str(card.card_type).upper() == "NPC":
                if card.name.lower() == name_lower or name_lower in card.name.lower():
                    power = card.content.get("power_level", llm_estimate) if isinstance(card.content, dict) else llm_estimate
                    return max(1, min(10, int(power)))
        return max(1, min(10, llm_estimate))

    async def _evaluate_power_update(self, narrative: str, player_input: str) -> dict | None:
        """Ask the LLM if the player's power level should change based on what just happened.

        Embedded as a lightweight check — only updates when narratively significant.
        Returns the power change dict if updated, None otherwise.
        """
        if not self._combat:
            return None
        power_scale = self._build_power_scale_reference()
        messages = [
            {
                "role": "system",
                "content": (
                    "You evaluate whether a player's power level should change after a story event. "
                    "Return ONLY JSON: "
                    '{"should_update": bool, "new_power": int, "reason": str}. '
                    f"Current player power: {self._player_power}/10. "
                    "Power ONLY changes with important story events that fundamentally alter "
                    "the character's capabilities — should_update=false for everything else. "
                    "Regular combat, exploration, conversations, and minor events do NOT change power. "
                    "Maximum change: ±1 per event (±2 only for truly extraordinary transformations). "
                    "new_power must be 0-10 and consistent with the world power scale below.\n"
                    + power_scale
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Player action: {player_input}\n"
                    f"Narrative result: {narrative[:500]}"
                ),
            },
        ]
        try:
            raw = await self._combat._llm.complete(messages=messages, max_tokens=128)
            data = parse_json_dict(raw)
            if data and data.get("should_update"):
                new_power = max(0, min(10, int(data.get("new_power", self._player_power))))
                if new_power != self._player_power:
                    old_power = self._player_power
                    self._player_power = new_power
                    reason = str(data.get("reason", ""))
                    self._event_store.append(
                        campaign_id=self.campaign_id,
                        event_type=EventType.POWER_LEVEL_UPDATE,
                        payload={
                            "target": "player",
                            "old_power": old_power,
                            "new_power": new_power,
                            "reason": reason,
                        },
                        narrative_time_delta=0,
                        location="current",
                        entities=["player"],
                    )
                    logger.info(
                        "Player power updated: %d -> %d (%s)",
                        old_power, new_power, reason,
                    )
                    return {"old_power": old_power, "new_power": new_power, "reason": reason}
        except Exception:
            logger.warning("Power level evaluation failed", exc_info=True)
        return None

    def _is_single_call_provider(self) -> bool:
        """Single-call mode disabled — all providers use the streaming path.

        The single-call JSON format is unreliable with large prompts (100k+
        chars of context causes the model to ignore the JSON format instruction
        and return plain narrative). Streaming path works for all providers.
        """
        return False

    def _get_context_window(self) -> int:
        """Return the context window size (tokens) for the current LLM provider."""
        try:
            return self._narrator._llm.config.get_context_window()
        except AttributeError:
            return 64_000

    # ── Story Card RAG ──────────────────────────────────────────────
    # Fraction of the provider's context window allocated to story cards.
    # The rest is split between system prompt, chat history, and output.
    _STORY_CARDS_CONTEXT_FRACTION = 0.15  # 15% of context window
    _STORY_CARDS_MIN_BUDGET = 4_000       # floor: always allow at least 4k tokens
    _STORY_CARDS_MAX_BUDGET = 40_000      # ceiling: never exceed 40k even on 1M windows
    _STORY_CARDS_MAX_COUNT = 50           # hard cap on number of cards regardless of budget

    # Bonus scores for card relevance ranking
    _LORE_BONUS = 100         # LORE cards (world rules) always rank highest
    _ACTIVE_NPC_BONUS = 50    # cards whose name matches an active NPC mind
    _MENTIONED_BONUS = 30     # cards mentioned by name in recent narrative/input
    _KEYWORD_MATCH_SCORE = 5  # per keyword hit in card content

    @staticmethod
    def _extract_context_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text for relevance matching."""
        if not text:
            return set()
        # Lowercase, split on whitespace and punctuation
        import re
        words = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text.lower())
        # Filter very common words (basic stop words for EN/PT)
        stop = {
            "the", "and", "for", "that", "this", "with", "you", "your", "are",
            "was", "were", "has", "have", "had", "been", "will", "not", "but",
            "from", "they", "she", "his", "her", "its", "our", "que", "para",
            "com", "uma", "por", "ele", "ela", "seu", "sua", "dos", "das",
            "nos", "nas", "mais", "como", "não", "está", "isso", "esse",
            "essa", "são", "tem", "foi", "ser", "ter", "mas", "quando",
            "sobre", "entre", "depois", "antes", "muito", "pode", "seus",
            "suas", "ainda", "também", "apenas", "cada", "outro", "outra",
        }
        return {w for w in words if w not in stop and len(w) > 2}

    def _compute_story_cards_budget(self) -> int:
        """Compute token budget for story cards based on provider context window."""
        context_window = self._get_context_window()
        budget = int(context_window * self._STORY_CARDS_CONTEXT_FRACTION)
        return max(self._STORY_CARDS_MIN_BUDGET, min(self._STORY_CARDS_MAX_BUDGET, budget))

    def _score_card_relevance(
        self,
        card,
        context_keywords: set[str],
        active_npc_names: set[str],
        mentioned_names: set[str],
    ) -> float:
        """Score a story card's relevance to the current context."""
        card_type = getattr(card, "card_type", "UNKNOWN")
        if hasattr(card_type, "value"):
            card_type = card_type.value
        card_name_lower = card.name.lower()

        score = 0.0

        # LORE cards always get highest priority (world rules)
        if card_type == "LORE":
            score += self._LORE_BONUS

        # Cards whose name matches an active NPC in the scene
        if card_name_lower in active_npc_names:
            score += self._ACTIVE_NPC_BONUS

        # Cards mentioned by name in recent text
        if card_name_lower in mentioned_names:
            score += self._MENTIONED_BONUS

        # Keyword overlap between card content and context
        content = card.content if isinstance(card.content, dict) else {}
        card_text = (card.name + " " + " ".join(str(v) for v in content.values())).lower()
        card_words = set(card_text.split())
        hits = len(context_keywords & card_words)
        score += hits * self._KEYWORD_MATCH_SCORE

        return score

    def _format_story_cards_context(
        self,
        player_input: str = "",
        recent_narrative: str = "",
    ) -> str:
        """Select and format story cards using RAG relevance scoring.

        Cards are ranked by relevance to the current context (player input,
        recent narrative, active NPCs) and included until the token budget
        is exhausted.  Budget scales with the provider's context window:
        ~30k tokens on DeepSeek (200k), ~40k on Anthropic (1M, capped).
        """
        if not self._story_cards:
            return ""

        budget = self._compute_story_cards_budget()

        # Build context for relevance scoring
        context_text = f"{player_input} {recent_narrative}"
        context_keywords = self._extract_context_keywords(context_text)

        # Collect active NPC names (lowercase) from NPC minds
        active_npc_names: set[str] = set()
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                active_npc_names.add(mind.name.lower())

        # Collect names explicitly mentioned in context text (lowercase)
        mentioned_names: set[str] = set()
        context_lower = context_text.lower()
        for card in self._story_cards:
            if card.name.lower() in context_lower:
                mentioned_names.add(card.name.lower())

        # Score all cards
        scored_cards: list[tuple[float, int, object]] = []
        for idx, card in enumerate(self._story_cards):
            score = self._score_card_relevance(
                card, context_keywords, active_npc_names, mentioned_names,
            )
            scored_cards.append((score, idx, card))

        # Sort by score descending (idx breaks ties for stable order)
        scored_cards.sort(key=lambda x: (-x[0], x[1]))

        # Fill budget with highest-relevance cards
        header = "WORLD LORE (story cards selected by relevance to current scene):"
        lines = [header]
        used_tokens = estimate_tokens(header)
        included = 0
        skipped = 0

        for score, _idx, card in scored_cards:
            if included >= self._STORY_CARDS_MAX_COUNT:
                skipped += len(scored_cards) - included - skipped
                break

            content = card.content if isinstance(card.content, dict) else {}
            card_type = getattr(card, "card_type", "UNKNOWN")
            if hasattr(card_type, "value"):
                card_type = card_type.value
            parts = [f"[{card_type}] {card.name}"]
            for k, v in content.items():
                if v:
                    parts.append(f"  {k}: {v}")
            card_text = "\n".join(parts)
            card_tokens = estimate_tokens(card_text)

            if used_tokens + card_tokens > budget:
                skipped += 1
                continue

            lines.append(card_text)
            used_tokens += card_tokens
            included += 1

        if skipped > 0:
            lines.append(
                f"\n(... {skipped} additional cards available but omitted — "
                f"budget {budget} tokens, used {used_tokens})"
            )

        logger.info(
            "Story cards RAG: included %d/%d (budget %d tokens, used %d, context_window %d)",
            included, len(self._story_cards), budget, used_tokens,
            self._get_context_window(),
        )

        return "\n".join(lines)

    def _verify_npc_seed_in_response(self, narrative_text: str) -> None:
        """Check if the pending NPC seed name appeared in the narrative response.

        If the name (or a close variant) is found, mark the seed as introduced
        and register it in the NPC minds. If not found, keep the seed pending
        so the hint is re-injected in the next action.
        """
        if not self._pending_npc_seed or self._pending_npc_introduced:
            return
        npc_name = self._pending_npc_seed.get("name", "")
        if not npc_name or not narrative_text:
            return

        # Check if the NPC name (or parts of it) appear in the response
        text_lower = narrative_text.lower()
        name_lower = npc_name.lower()
        name_parts = name_lower.split()

        # Match: full name, or first name, or last name (for "Kaito Zenin" → "Kaito" or "Zenin")
        found = name_lower in text_lower or any(
            part in text_lower for part in name_parts if len(part) > 2
        )

        if found:
            self._pending_npc_introduced = True
            # Register in NPC minds so the name persists in future prompts
            if self._npc_minds:
                mind = self._npc_minds._ensure_mind(self.campaign_id, npc_name)
                npc = self._pending_npc_seed
                mind.set_thought("feeling", npc.get("personality", "observing"))
                mind.set_thought("goal", npc.get("goal", "unknown"))
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.NPC_THOUGHT,
                    payload={
                        "name": mind.name,
                        "thoughts": {k: t.value for k, t in mind.thoughts.items()},
                        "aliases": mind.aliases,
                    },
                    narrative_time_delta=0,
                    location="npc_mind",
                    entities=[mind.name],
                )
            logger.info("NPC seed '%s' confirmed in narrative — marked as introduced", npc_name)
        else:
            logger.info(
                "NPC seed '%s' NOT found in narrative — keeping pending for next action",
                npc_name,
            )

    async def process_action(self, player_input: str, max_tokens: int = 2000) -> AsyncIterator[str]:
        self._max_tokens = max_tokens

        # Single-call mode for Anthropic: one LLM call does everything
        if self._is_single_call_provider():
            async for chunk in self._process_action_single_call(player_input, max_tokens):
                yield chunk
            return

        story_ctx = self._history[-1]["content"][:300] if self._history else ""
        power_scale = self._build_power_scale_reference()
        if power_scale:
            story_ctx += "\n" + power_scale
        mode, meta = await self._narrator.detect_mode(player_input, story_context=story_ctx)
        mode = self._coerce_mode(mode)
        narrative_time = meta.get("narrative_time_seconds", 60)
        if mode != NarrativeMode.META:
            self._turn_count += 1

        self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.PLAYER_ACTION,
            payload={"text": player_input, "mode": mode.value},
            narrative_time_delta=narrative_time,
            location="current",
            entities=["player"],
        )

        player_entry = None
        try:
            log_player_action = getattr(self._journal, "log_player_action", None)
            if callable(log_player_action):
                player_entry = log_player_action(self.campaign_id, player_input)
        except Exception:
            logger.warning("Player action journal logging failed", exc_info=True)

        if self._is_journal_entry(player_entry):
            payload = {
                "category": player_entry.category.value,
                "summary": player_entry.summary,
                "created_at": player_entry.created_at,
            }
            yield f"[JOURNAL]{json.dumps(payload)}"

        # Emit mode signal for frontend combat overlay
        yield f"[MODE]{mode.value}"

        if mode == NarrativeMode.COMBAT and self._combat:
            async for chunk in self._handle_combat(player_input, meta):
                yield chunk
        else:
            async for chunk in self._handle_narrative(player_input, mode):
                yield chunk

        if mode != NarrativeMode.META:
            if self._graphiti:
                world_ctx = await self._memory.build_context_window_async(self.campaign_id)
            else:
                world_ctx = self._memory.build_context_window(self.campaign_id)
            world_changes = await self._world_reactor.process_tick(
                campaign_id=self.campaign_id,
                narrative_seconds=narrative_time,
                world_context=world_ctx,
                language=self.language,
            )
            if world_changes:
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.WORLD_TICK,
                    payload={"text": world_changes},
                    narrative_time_delta=0,
                    location="world",
                    entities=[],
                )
                await self._ingest_to_graphiti(world_changes, "world_tick")

            try:
                async for chunk in self._maybe_trigger_auto_plot(world_ctx):
                    yield chunk
            except Exception:
                logger.warning("Auto plot generation failed", exc_info=True)

    def _resolve_canonical_name(self, short_name: str, all_names: list[str]) -> str:
        """Resolve a potentially short name to its full canonical form.

        E.g. 'ShortName' -> 'Full Canonical Name'.
        Returns the original name if no better match is found.
        """
        lower = short_name.lower()
        # Already a long name or exact match? Return as-is.
        for full in all_names:
            if full.lower() == lower:
                return full
        # Check if short_name is a substring of a longer known name
        for full in all_names:
            if lower in full.lower() and len(full) > len(short_name):
                return full
        return short_name

    async def get_graph_relationship_summary(self) -> str:
        """Query the graph engine for entity relationships and format as a concise string.

        Returns a readable summary of the most relevant relationships (max ~20)
        for injection into the narrator's system prompt. Returns empty string if
        the graph engine is unavailable or has no data.
        """
        if not self._graph:
            return ""
        try:
            nodes = await self._graph.get_all_nodes()
            relationships = await self._graph.get_all_relationships()
            if not relationships:
                return ""

            # Build node_id -> name lookup
            id_to_name: dict[str, str] = {n.id: n.name for n in nodes}

            # Collect all known names for canonical resolution
            all_names = [n.name for n in nodes]
            if self._npc_minds:
                for mind in self._npc_minds.get_all_minds(self.campaign_id):
                    if mind.name not in all_names:
                        all_names.append(mind.name)

            # Format relationships as readable lines, cap at 20
            lines: list[str] = []
            for rel in relationships[:20]:
                source_raw = id_to_name.get(rel["source_id"], "Unknown")
                target_raw = id_to_name.get(rel["target_id"], "Unknown")
                source = self._resolve_canonical_name(source_raw, all_names)
                target = self._resolve_canonical_name(target_raw, all_names)
                rel_type = rel["rel_type"].replace("_", " ")
                lines.append(f"- {source} {rel_type} {target}")

            return "\n".join(lines)
        except Exception:
            logger.warning("Failed to build graph relationship summary", exc_info=True)
            return ""

    async def _handle_narrative(self, player_input: str, mode: NarrativeMode = NarrativeMode.NARRATIVE, combat_outcome: str = "", combat_opponent_name: str = "", combat_npc_power: int = 5) -> AsyncIterator[str]:
        if self._graphiti:
            memory_ctx = await self._memory.build_context_window_async(self.campaign_id)
        else:
            memory_ctx = self._memory.build_context_window(self.campaign_id)

        if mode == NarrativeMode.META:
            system_prompt = self._build_meta_system_prompt()
        else:
            inventory_ctx = ""
            if self._inventory:
                inventory_ctx = self._inventory.format_for_prompt(self.campaign_id)
            # Build narrator hints from active plot seeds, micro-hooks, and NPC seeds
            narrator_hints = ""
            if self._active_plot_seeds:
                seeds = "\n".join(f"- {s}" for s in self._active_plot_seeds[-3:])
                narrator_hints += f"\nFUTURE PLOT SEEDS (foreshadow subtly, do NOT resolve yet):\n{seeds}"
            if self._pending_micro_hook:
                narrator_hints += f"\nMICRO-HOOK (weave this detail naturally into your response):\n{self._pending_micro_hook}"
                self._pending_micro_hook = ""  # consumed
            if self._pending_npc_seed and not self._pending_npc_introduced:
                npc = self._pending_npc_seed
                npc_name = npc.get('name', 'Unknown')
                narrator_hints += (
                    f"\nNEW NPC TO INTRODUCE — YOU MUST USE THIS EXACT NAME: \"{npc_name}\"\n"
                    f"(Weave this character into the scene naturally — "
                    f"have them appear and interact with the player. "
                    f"The character's name is {npc_name}. Use this name in the narrative text. "
                    f"Do NOT substitute a different name or use a canonical character instead.)\n"
                    f"Name: {npc_name}\n"
                    f"Appearance: {npc.get('appearance', '')}\n"
                    f"Personality: {npc.get('personality', '')}\n"
                    f"Goal: {npc.get('goal', '')}\n"
                    f"Power Level: {npc.get('power_level', 5)}/10"
                )
                # Do NOT mark as introduced yet — we verify after the narrative response

            if combat_outcome:
                narrator_hints += self._build_combat_narrator_hint(
                    combat_outcome,
                    opponent_name=combat_opponent_name,
                    opponent_power=combat_npc_power,
                    player_power=self._player_power,
                )

            graph_ctx = await self.get_graph_relationship_summary()

            npc_ctx = ""
            if self._npc_minds:
                minds = self._npc_minds.get_all_minds(self.campaign_id)
                if minds:
                    lines = ["NPC STATES (what each NPC is currently thinking/feeling):"]
                    for m in minds[:10]:
                        thoughts = ", ".join(f"{k}={t.value}" for k, t in list(m.thoughts.items())[:4])
                        lines.append(f"- {m.name}: {thoughts}")
                    npc_ctx = "\n".join(lines)

            journal_ctx = ""
            if self._journal:
                try:
                    entries = self._journal.get_journal(self.campaign_id)
                    if entries:
                        lines = ["STORY LOG (key events so far):"]
                        for e in entries[-8:]:
                            lines.append(f"- {e.summary}")
                        journal_ctx = "\n".join(lines)
                except Exception:
                    pass

            system_prompt = self._narrator.build_system_prompt(
                tone_instructions=self.scenario_tone,
                memory_context=memory_ctx,
                language=self.language,
                inventory_context=inventory_ctx,
                max_tokens=getattr(self, '_max_tokens', 2000),
                narrator_hints=narrator_hints,
                graph_context=graph_ctx,
                npc_context=npc_ctx,
                journal_context=journal_ctx,
                story_cards_context=self._format_story_cards_context(
                    player_input=player_input,
                    recent_narrative=self._history[-1]["content"][:1000] if self._history else "",
                ),
            )

        # Collect full response before sending to frontend (no streaming)
        context_window = self._get_context_window()
        full_response = ""
        async for chunk in self._narrator.stream_narrative(
            player_input, system_prompt, self._history,
            context_window=context_window,
        ):
            full_response += chunk

        # Auto-continuation: if the response was truncated mid-sentence,
        # ask the LLM to finish instead of just trimming.
        if full_response and not self._is_response_complete(full_response):
            continuation_prompt = (
                "Continue the narrative EXACTLY where you stopped. "
                "Do NOT repeat any text. Complete the current sentence and paragraph, "
                "then end at a natural pause point. Keep the same tone and language."
            )
            continuation_history = self._history + [
                {"role": "user", "content": player_input},
                {"role": "assistant", "content": full_response},
            ]
            async for chunk in self._narrator.stream_narrative(
                continuation_prompt, system_prompt, continuation_history,
                context_window=context_window,
            ):
                full_response += chunk

        # Final cleanup: trim truncation and fix number spacing
        cleaned = self._clean_truncated_response(full_response)
        cleaned = self._fix_number_spacing(cleaned)
        full_response = cleaned

        # Send the clean narrative to frontend (all at once)
        yield full_response

        # Process inventory tags from response
        clean_response = full_response
        if self._inventory:
            clean_response, inv_events = self._extract_inventory_tags(full_response)
            for inv_event in inv_events:
                self._apply_inventory_event(inv_event)
                yield f"[INVENTORY]{json.dumps(inv_event)}"

        # Verify NPC seed introduction: check if the NPC name appeared in the response
        self._verify_npc_seed_in_response(clean_response)

        # Record in history and event store
        self._history.append({"role": "user", "content": player_input})
        self._history.append({"role": "assistant", "content": clean_response})
        self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.NARRATOR_RESPONSE,
            payload={"text": clean_response},
            narrative_time_delta=0,
            location="current",
            entities=[],
        )

        # Journal evaluation
        entry = await self._journal.evaluate_and_log(self.campaign_id, clean_response)
        if self._is_journal_entry(entry):
            yield f"[JOURNAL]{json.dumps({'category': entry.category.value, 'summary': entry.summary, 'created_at': entry.created_at})}"

        # Post-narrative side effects (only for non-META actions)
        if mode != NarrativeMode.META and clean_response:
            async for chunk in self._post_narrative_pipeline(clean_response):
                yield chunk

    async def _process_action_single_call(self, player_input: str, max_tokens: int) -> AsyncIterator[str]:
        """Single LLM call mode for Anthropic: narrative + mode + NPCs + entities in one request."""
        # Detect mode first so combat pipeline runs before the main LLM call
        story_ctx = self._history[-1]["content"][:300] if self._history else ""
        power_scale = self._build_power_scale_reference()
        if power_scale:
            story_ctx += "\n" + power_scale
        mode, meta = await self._narrator.detect_mode(player_input, story_context=story_ctx)
        mode = self._coerce_mode(mode)
        narrative_time = meta.get("narrative_time_seconds", 60)
        if mode != NarrativeMode.META:
            self._turn_count += 1

        # Persist player action (same as streaming path)
        self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.PLAYER_ACTION,
            payload={"text": player_input, "mode": mode.value},
            narrative_time_delta=narrative_time,
            location="current",
            entities=["player"],
        )

        # Journal for player action
        try:
            log_player_action = getattr(self._journal, "log_player_action", None)
            if callable(log_player_action):
                player_entry = log_player_action(self.campaign_id, player_input)
                if self._is_journal_entry(player_entry):
                    yield f"[JOURNAL]{json.dumps({'category': player_entry.category.value, 'summary': player_entry.summary, 'created_at': player_entry.created_at})}"
        except Exception:
            pass

        yield f"[MODE]{mode.value}"

        # Combat pipeline: anti-griefing, evaluate, roll (same as streaming path)
        combat_outcome = ""
        combat_quality = 0.0
        combat_opponent_name = ""
        combat_npc_power = 5
        if mode == NarrativeMode.COMBAT and self._combat:
            try:
                griefing = await self._combat.anti_griefing_check(player_input, language=self.language)
                if griefing.rejected:
                    rejection_text = griefing.reason
                    yield rejection_text
                    self._history.append({"role": "user", "content": player_input})
                    self._history.append({"role": "assistant", "content": rejection_text})
                    self._event_store.append(
                        campaign_id=self.campaign_id,
                        event_type=EventType.NARRATOR_RESPONSE,
                        payload={"text": rejection_text},
                        narrative_time_delta=0,
                        location="current",
                        entities=[],
                    )
                    return

                combat_opponent_name = meta.get("opponent_name", "opponent")
                llm_estimate = meta.get("opponent_power", 5)
                combat_npc_power = self._resolve_opponent_power(combat_opponent_name, llm_estimate)
                evaluation = await self._combat.evaluate_action(
                    action=player_input,
                    npc_name=combat_opponent_name or "opponent",
                    npc_power=combat_npc_power,
                )
                outcome = self._combat.roll_outcome(evaluation.final_quality, combat_npc_power)
                combat_outcome = outcome.value if hasattr(outcome, "value") else str(outcome)
                combat_quality = evaluation.final_quality

                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.COMBAT_RESULT,
                    payload={
                        "outcome": combat_outcome,
                        "quality": combat_quality,
                        "opponent_name": combat_opponent_name,
                        "opponent_power": combat_npc_power,
                        "player_power": self._player_power,
                    },
                    narrative_time_delta=0,
                    location="current",
                    entities=["player"],
                )

                yield (
                    f"[Combat: {combat_opponent_name} (power {combat_npc_power}) "
                    f"vs Player (power {self._player_power}) → {combat_outcome}] "
                )
            except Exception:
                logger.warning("Combat engine failed in single-call path", exc_info=True)

        # Build context (same as _handle_narrative)
        if self._graphiti:
            memory_ctx = await self._memory.build_context_window_async(self.campaign_id)
        else:
            memory_ctx = self._memory.build_context_window(self.campaign_id)

        inventory_ctx = ""
        if self._inventory:
            inventory_ctx = self._inventory.format_for_prompt(self.campaign_id)

        narrator_hints = ""
        if self._active_plot_seeds:
            seeds = "\n".join(f"- {s}" for s in self._active_plot_seeds[-3:])
            narrator_hints += f"\nFUTURE PLOT SEEDS (foreshadow subtly, do NOT resolve yet):\n{seeds}"
        if self._pending_micro_hook:
            narrator_hints += f"\nMICRO-HOOK (weave this detail naturally into your response):\n{self._pending_micro_hook}"
            self._pending_micro_hook = ""
        if self._pending_npc_seed and not self._pending_npc_introduced:
            npc = self._pending_npc_seed
            npc_name = npc.get('name', 'Unknown')
            narrator_hints += (
                f"\nNEW NPC TO INTRODUCE — YOU MUST USE THIS EXACT NAME: \"{npc_name}\"\n"
                f"(Weave this character into the scene naturally — "
                f"have them appear and interact with the player. "
                f"The character's name is {npc_name}. Use this name in the narrative text. "
                f"Do NOT substitute a different name or use a canonical character instead.)\n"
                f"Name: {npc_name}\n"
                f"Appearance: {npc.get('appearance', '')}\n"
                f"Personality: {npc.get('personality', '')}\n"
                f"Goal: {npc.get('goal', '')}\n"
                f"Power Level: {npc.get('power_level', 5)}/10"
            )
            # Do NOT mark as introduced yet — we verify after the narrative response

        if combat_outcome:
            narrator_hints += self._build_combat_narrator_hint(
                combat_outcome,
                opponent_name=combat_opponent_name,
                opponent_power=combat_npc_power,
                player_power=self._player_power,
            )

        graph_ctx = await self.get_graph_relationship_summary()

        npc_ctx = ""
        if self._npc_minds:
            minds = self._npc_minds.get_all_minds(self.campaign_id)
            if minds:
                lines = ["NPC STATES (what each NPC is currently thinking/feeling):"]
                for m in minds[:10]:
                    thoughts = ", ".join(f"{k}={t.value}" for k, t in list(m.thoughts.items())[:4])
                    lines.append(f"- {m.name}: {thoughts}")
                npc_ctx = "\n".join(lines)

        journal_ctx = ""
        if self._journal:
            try:
                entries = self._journal.get_journal(self.campaign_id)
                if entries:
                    lines = ["STORY LOG (key events so far):"]
                    for e in entries[-8:]:
                        lines.append(f"- {e.summary}")
                    journal_ctx = "\n".join(lines)
            except Exception:
                pass

        static_prompt, dynamic_prompt = self._narrator.build_system_prompt_parts(
            tone_instructions=self.scenario_tone,
            memory_context=memory_ctx,
            language=self.language,
            inventory_context=inventory_ctx,
            max_tokens=max_tokens,
            narrator_hints=narrator_hints,
            graph_context=graph_ctx,
            npc_context=npc_ctx,
            journal_context=journal_ctx,
            story_cards_context=self._format_story_cards_context(
                player_input=player_input,
                recent_narrative=self._history[-1]["content"][:1000] if self._history else "",
            ),
        )

        # Collect canonical names for entity extraction
        canonical_names: list[str] = []
        if self._graph:
            try:
                existing_nodes = await self._graph.get_all_nodes()
                canonical_names = [n.name for n in existing_nodes]
            except Exception:
                pass
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                if mind.name not in canonical_names:
                    canonical_names.append(mind.name)

        # Single LLM call with prompt caching on static part
        context_window = self._get_context_window()
        result = await self._narrator.complete_single_call(
            player_input=player_input,
            static_prompt=static_prompt,
            dynamic_prompt=dynamic_prompt,
            history=self._history,
            canonical_names=canonical_names,
            max_tokens=max_tokens,
            context_window=context_window,
        )

        # Get narrative text and emit it all at once
        full_response = result.get("narrative_text", "")
        already_emitted = False

        # Auto-continuation for single-call: if truncated, do a streaming continuation
        if full_response and not self._is_response_complete(full_response):
            yield full_response  # emit what we have so far
            already_emitted = True
            continuation_prompt = (
                "Continue the narrative EXACTLY where you stopped. "
                "Do NOT repeat any text. Complete the current sentence and paragraph, "
                "then end at a natural pause point. Keep the same tone and language."
            )
            continuation_history = self._history + [
                {"role": "user", "content": player_input},
                {"role": "assistant", "content": full_response},
            ]
            system_prompt = static_prompt + "\n" + dynamic_prompt
            async for chunk in self._narrator.stream_narrative(
                continuation_prompt, system_prompt, continuation_history,
                context_window=context_window,
            ):
                full_response += chunk
                yield chunk

        cleaned = self._clean_truncated_response(full_response)
        # Fix numbers glued to words (common LLM output artifact)
        cleaned = self._fix_number_spacing(cleaned)
        if already_emitted and cleaned != full_response:
            yield f"[TRUNCATE_CLEAN]{cleaned}"

        # Process inventory tags
        clean_response = cleaned
        if self._inventory:
            clean_response, inv_events = self._extract_inventory_tags(cleaned)
            for inv_event in inv_events:
                self._apply_inventory_event(inv_event)
                yield f"[INVENTORY]{json.dumps(inv_event)}"

        # Emit full narrative (skip if already streamed via auto-continuation)
        if not already_emitted:
            yield clean_response

        # Verify NPC seed introduction: check if the NPC name appeared in the response
        self._verify_npc_seed_in_response(clean_response)

        # Record in history and event store
        self._history.append({"role": "user", "content": player_input})
        self._history.append({"role": "assistant", "content": clean_response})
        self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.NARRATOR_RESPONSE,
            payload={"text": clean_response},
            narrative_time_delta=0,
            location="current",
            entities=[],
        )

        # Journal evaluation for narrative
        entry = await self._journal.evaluate_and_log(self.campaign_id, clean_response)
        if self._is_journal_entry(entry):
            yield f"[JOURNAL]{json.dumps({'category': entry.category.value, 'summary': entry.summary, 'created_at': entry.created_at})}"

        # Combat journal entry (same as streaming path)
        if combat_outcome and clean_response:
            combat_summary = (
                f"Combat action: {player_input}. "
                f"Opponent: {combat_opponent_name} (power {combat_npc_power}). "
                f"Player power: {self._player_power}. "
                f"Outcome: {combat_outcome}. Quality: {combat_quality}/10."
            )
            combat_entry = await self._journal.evaluate_and_log(self.campaign_id, combat_summary)
            if self._is_journal_entry(combat_entry):
                yield f"[JOURNAL]{json.dumps({'category': combat_entry.category.value, 'summary': combat_entry.summary, 'created_at': combat_entry.created_at})}"

            # Evaluate player power update after combat
            power_change = await self._evaluate_power_update(clean_response, player_input)
            if power_change:
                yield f"[POWER]{json.dumps(power_change)}"

        # Apply side effects from the single-call result
        if mode != NarrativeMode.META and clean_response:
            # NPC thoughts from result (use async dedup for fuzzy matching parity)
            npc_thoughts = result.get("npc_thoughts", [])
            if npc_thoughts and self._npc_minds:
                try:
                    for npc_data in npc_thoughts:
                        name = npc_data.get("name", "").lstrip("@").strip()
                        if not name:
                            continue
                        mind = await self._npc_minds._ensure_mind_async(self.campaign_id, name)
                        for key, value in npc_data.get("thoughts", {}).items():
                            if value:
                                mind.set_thought(key, str(value))
                        self._event_store.append(
                            campaign_id=self.campaign_id,
                            event_type=EventType.NPC_THOUGHT,
                            payload={
                                "name": mind.name,
                                "thoughts": {k: t.value for k, t in mind.thoughts.items()},
                                "aliases": mind.aliases,
                            },
                            narrative_time_delta=0,
                            location="npc_mind",
                            entities=[mind.name],
                        )
                except Exception:
                    logger.warning("Single-call NPC thought processing failed", exc_info=True)

            # Entities and relationships from result
            if self._graph:
                try:
                    from app.engines.graph_engine import WorldNodeType
                    name_to_id: dict[str, str] = {}
                    existing = await self._graph.get_all_nodes()
                    for node in existing:
                        name_to_id[node.name.lower()] = node.id

                    for entity in result.get("entities", []):
                        name = entity.get("name", "").strip()
                        if not name:
                            continue
                        existing_id = self._find_existing_node_id(name, name_to_id)
                        if existing_id:
                            name_to_id[name.lower()] = existing_id
                            continue
                        try:
                            node_type = WorldNodeType(entity.get("type", "NPC"))
                        except ValueError:
                            node_type = WorldNodeType.NPC
                        node = await self._graph.add_node(
                            node_type=node_type,
                            name=name,
                            attributes=entity.get("attributes", {}),
                        )
                        name_to_id[name.lower()] = node.id

                    for rel in result.get("relationships", []):
                        source_name = rel.get("source", "").strip()
                        target_name = rel.get("target", "").strip()
                        rel_type = rel.get("rel_type", "RELATED_TO")
                        source_id = self._find_existing_node_id(source_name, name_to_id)
                        target_id = self._find_existing_node_id(target_name, name_to_id)
                        if source_id and target_id and source_id != target_id:
                            await self._graph.add_relationship(source_id, target_id, rel_type)
                except Exception:
                    logger.warning("Single-call graph extraction failed", exc_info=True)

            # World changes from result
            world_changes = result.get("world_changes", "")
            if world_changes:
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.WORLD_TICK,
                    payload={"text": world_changes},
                    narrative_time_delta=0,
                    location="world",
                    entities=[],
                )

            # Memory crystallization (still needed — local operation, no LLM unless threshold hit)
            crystal = await self._try_auto_crystallize()
            if crystal:
                yield f"[CRYSTAL]{json.dumps({'tier': crystal.tier.value, 'event_count': crystal.event_count})}"

            # Graphiti ingestion
            await self._ingest_to_graphiti(clean_response, "narrator_response")

            # World reactor tick (uses separate LLM call only for non-MICRO ticks)
            if self._graphiti:
                world_ctx = await self._memory.build_context_window_async(self.campaign_id)
            else:
                world_ctx = self._memory.build_context_window(self.campaign_id)
            reactor_changes = await self._world_reactor.process_tick(
                campaign_id=self.campaign_id,
                narrative_seconds=narrative_time,
                world_context=world_ctx,
                language=self.language,
            )
            if reactor_changes:
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.WORLD_TICK,
                    payload={"text": reactor_changes},
                    narrative_time_delta=0,
                    location="world",
                    entities=[],
                )
                await self._ingest_to_graphiti(reactor_changes, "world_tick")

            # Auto plot
            try:
                async for chunk in self._maybe_trigger_auto_plot(world_ctx):
                    yield chunk
            except Exception:
                logger.warning("Auto plot generation failed", exc_info=True)

    def _apply_inventory_event(self, inv_event: dict) -> None:
        """Apply a single inventory event (add/use/lose)."""
        action = inv_event["action"]
        if action == "add":
            self._inventory.add_item(
                self.campaign_id, inv_event["name"],
                inv_event.get("category", "misc"), inv_event.get("source", "unknown"),
            )
        elif action == "use":
            self._inventory.use_item(self.campaign_id, inv_event["name"])
        elif action == "lose":
            self._inventory.lose_item(self.campaign_id, inv_event["name"])

    async def _post_narrative_pipeline(self, clean_response: str) -> AsyncIterator[str]:
        """Run all post-narrative side effects: NPC minds, graph, memory, graphiti, power."""
        logger.info("_post_narrative_pipeline: starting (response %d chars)", len(clean_response))
        await self._update_npc_minds(clean_response)
        await self._extract_to_graph(clean_response)

        crystal = await self._try_auto_crystallize()
        if crystal:
            yield f"[CRYSTAL]{json.dumps({'tier': crystal.tier.value, 'event_count': crystal.event_count})}"

        await self._ingest_to_graphiti(clean_response, "narrator_response")

        # Evaluate player power changes from non-combat events too
        # (e.g., absorbing artifacts, training, crippling injuries)
        last_player_input = ""
        if len(self._history) >= 2:
            last_player_input = self._history[-2].get("content", "")
        power_change = await self._evaluate_power_update(clean_response, last_player_input)
        if power_change:
            yield f"[POWER]{json.dumps(power_change)}"

    async def _update_npc_minds(self, narrative_text: str) -> None:
        if not self._npc_minds or not narrative_text:
            logger.warning("_update_npc_minds skipped: npc_minds=%s, narrative_len=%d",
                           bool(self._npc_minds), len(narrative_text) if narrative_text else 0)
            return
        logger.info("_update_npc_minds: starting for campaign %s (narrative %d chars)",
                    self.campaign_id, len(narrative_text))
        try:
            if self._graphiti:
                world_ctx = await self._memory.build_context_window_async(self.campaign_id)
            else:
                world_ctx = self._memory.build_context_window(self.campaign_id)
            updated = await self._npc_minds.update_npc_thoughts(
                campaign_id=self.campaign_id,
                narrative_text=narrative_text,
                world_context=world_ctx,
                language=self.language,
            )
            # Persist NPC thoughts so they survive server restarts
            for mind in updated:
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.NPC_THOUGHT,
                    payload={
                        "name": mind.name,
                        "thoughts": {k: t.value for k, t in mind.thoughts.items()},
                        "aliases": mind.aliases,
                    },
                    narrative_time_delta=0,
                    location="npc_mind",
                    entities=[mind.name],
                )
        except Exception:
            logger.error(
                "NPC mind update failed for campaign %s (narrative length: %d chars)",
                self.campaign_id,
                len(narrative_text),
                exc_info=True,
            )

    async def _extract_to_graph(self, narrative_text: str) -> None:
        if not self._graph or not narrative_text:
            return
        try:
            await self._extract_entities_to_graph(narrative_text)
        except Exception:
            logger.warning("Graph entity extraction failed", exc_info=True)

    async def _try_auto_crystallize(self):
        try:
            return await self._memory.auto_crystallize_if_needed(self.campaign_id)
        except Exception:
            logger.warning("Auto-crystallization failed", exc_info=True)
            return None

    async def _ingest_to_graphiti(self, text: str, description: str) -> None:
        if not self._graphiti or not text:
            return
        try:
            await self._graphiti.ingest_episode(
                campaign_id=self.campaign_id,
                text=text,
                description=description,
            )
        except Exception:
            logger.warning("Graphiti %s ingestion failed", description, exc_info=True)

    def _build_meta_system_prompt(self) -> str:
        inventory_ctx = ""
        if self._inventory:
            inventory_ctx = self._inventory.format_for_prompt(self.campaign_id)

        journal_ctx = ""
        try:
            entries = self._journal.get_journal(self.campaign_id)
            if entries:
                journal_ctx = "\n".join(
                    f"- [{e.category.value}] {e.summary} ({e.created_at})"
                    for e in entries[-10:]
                )
        except Exception:
            pass

        npc_ctx = ""
        if self._npc_minds:
            minds = self._npc_minds.get_all_minds(self.campaign_id)
            if minds:
                lines = []
                for m in minds:
                    thoughts_summary = ", ".join(
                        f"{k}: {t.value}" for k, t in list(m.thoughts.items())[:3]
                    )
                    lines.append(f"- {m.name}: {thoughts_summary}")
                npc_ctx = "\n".join(lines)

        return self._narrator.build_meta_prompt(
            language=self.language,
            inventory_context=inventory_ctx,
            journal_context=journal_ctx,
            npc_context=npc_ctx,
        )

    async def _maybe_trigger_auto_plot(self, world_context: str) -> AsyncIterator[str]:
        if not self._plot_generator or not self._auto_plot_rules:
            return

        # Plot lock: block new auto-plot until current element is consumed.
        if self._plot_pending:
            turns_since_plot = self._turn_count - self._plot_pending_since_turn
            consumed = False

            if self._pending_npc_seed:
                # NPC lock: require introduction + minimum development turns
                if self._pending_npc_introduced and turns_since_plot >= self._PLOT_CONSUME_TURNS:
                    consumed = True
                    self._pending_npc_seed = None
                    self._pending_npc_introduced = False
            else:
                # Non-NPC plots: standard timer
                if turns_since_plot >= self._PLOT_CONSUME_TURNS:
                    consumed = True

            if consumed:
                self._plot_pending = False
                logger.info("Plot lock released after %d turns for campaign %s",
                            turns_since_plot, self.campaign_id)
            else:
                return  # Block all auto-plot while element is active

        safe_context = world_context or "(no context yet)"
        total_narrative_time = self._event_store.get_total_narrative_time(self.campaign_id)

        # Get the last narrator response for scene context
        recent_narrative = ""
        for msg in reversed(self._history):
            if msg["role"] == "assistant":
                recent_narrative = msg["content"][:500]
                break

        # Only one auto-trigger per turn to avoid noisy output.
        for kind in ("plot_arc", "micro_hook", "npc"):
            rule = self._auto_plot_rules.get(kind)
            if not rule:
                continue

            state = self._auto_plot_state.setdefault(
                kind,
                {"last_turn": 0, "last_narrative_time": 0, "trigger_count": 0},
            )
            turns_since_last = max(0, self._turn_count - state["last_turn"])
            seconds_since_last = max(0, total_narrative_time - state["last_narrative_time"])

            should_trigger = self._plot_generator.should_trigger_auto(
                rule=rule,
                turns_since_last=turns_since_last,
                narrative_seconds_since_last=seconds_since_last,
                trigger_count=state["trigger_count"],
            )
            if not should_trigger:
                continue

            payload: dict | None = None
            tone = self.scenario_tone or ""

            if kind == "npc":
                # Collect existing NPC names to avoid duplicates
                existing_names = []
                if self._npc_minds:
                    existing_names = [m.name for m in self._npc_minds.get_all_minds(self.campaign_id)]
                if self._pending_npc_seed:
                    existing_names.append(self._pending_npc_seed.get("name", ""))

                npc = await self._plot_generator.generate_npc(
                    safe_context,
                    language=self.language,
                    recent_narrative=recent_narrative,
                    existing_npc_names=existing_names,
                    tone_instructions=tone,
                )
                if npc is None:
                    # LLM decided it doesn't make sense right now — skip
                    logger.info("Auto-plot NPC skipped (NONE) for campaign %s", self.campaign_id)
                    continue
                npc_data = asdict(npc)
                payload = {"kind": kind, "source": "auto", "data": npc_data}
                # Store as pending NPC seed — narrator will introduce on next turn
                self._pending_npc_seed = npc_data
                self._pending_npc_introduced = False
                # NPC seeds are shown to the player
                yield f"[PLOT_AUTO]{json.dumps(payload, ensure_ascii=False)}"
            elif kind == "micro_hook":
                hook = await self._plot_generator.generate_micro_hook(
                    safe_context, recent_narrative,
                    language=self.language,
                    tone_instructions=tone,
                )
                if hook is None:
                    logger.info("Auto-plot micro_hook skipped (NONE) for campaign %s", self.campaign_id)
                    continue
                self._pending_micro_hook = hook.description
                payload = {"kind": kind, "source": "auto", "data": {"text": hook.description}}
                # Micro-hooks are NOT shown to the player — they are
                # injected into the narrator's system prompt for the next turn
            else:  # plot_arc
                arc = await self._plot_generator.generate_plot_arc(
                    safe_context, language=self.language,
                    recent_narrative=recent_narrative,
                    tone_instructions=tone,
                )
                if arc is None:
                    logger.info("Auto-plot plot_arc skipped (NONE) for campaign %s", self.campaign_id)
                    continue
                self._active_plot_seeds.append(arc)
                payload = {"kind": kind, "source": "auto", "data": {"text": arc}}
                # Plot arcs are NOT shown to the player — they are fed to
                # the narrator as "future plot seeds" for subtle foreshadowing

            self._event_store.append(
                campaign_id=self.campaign_id,
                event_type=EventType.PLOT_GENERATION,
                payload=payload,
                narrative_time_delta=0,
                location="plot",
                entities=[],
            )

            state["last_turn"] = self._turn_count
            state["last_narrative_time"] = total_narrative_time
            state["trigger_count"] += 1

            # Lock: block new plots until this one is consumed
            self._plot_pending = True
            self._plot_pending_since_turn = self._turn_count
            break

    async def _handle_combat(self, player_input: str, meta: dict) -> AsyncIterator[str]:
        try:
            griefing = await self._combat.anti_griefing_check(player_input, language=self.language)
            if griefing.rejected:
                rejection_text = griefing.reason
                yield rejection_text
                # Persist the rejection so META mode and history have context
                self._history.append({"role": "user", "content": player_input})
                self._history.append({"role": "assistant", "content": rejection_text})
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.NARRATOR_RESPONSE,
                    payload={"text": rejection_text},
                    narrative_time_delta=0,
                    location="current",
                    entities=[],
                )
                return

            opponent_name = meta.get("opponent_name", "opponent")
            llm_estimate = meta.get("opponent_power", 5)
            npc_power = self._resolve_opponent_power(opponent_name, llm_estimate)
            evaluation = await self._combat.evaluate_action(
                action=player_input,
                npc_name=opponent_name or "opponent",
                npc_power=npc_power,
            )
            outcome = self._combat.roll_outcome(evaluation.final_quality, npc_power)
            outcome_value = outcome.value if hasattr(outcome, "value") else str(outcome)

            self._event_store.append(
                campaign_id=self.campaign_id,
                event_type=EventType.COMBAT_RESULT,
                payload={
                    "outcome": outcome_value,
                    "quality": evaluation.final_quality,
                    "opponent_name": opponent_name,
                    "opponent_power": npc_power,
                    "player_power": self._player_power,
                },
                narrative_time_delta=0,
                location="current",
                entities=["player"],
            )

            # Prepend outcome hint for narrator
            outcome_hint = (
                f"[Combat: {opponent_name} (power {npc_power}) vs Player (power {self._player_power}) "
                f"→ {outcome_value}] "
            )
            yield outcome_hint

            # Inject combat outcome into the player input itself so the LLM cannot ignore it.
            # The system prompt hint alone is insufficient — DeepSeek often overrides FAIL outcomes.
            outcome_injected_input = player_input
            if outcome_value in ("FAIL", "CRIT_FAIL"):
                outcome_injected_input = (
                    f"[SYSTEM: The dice determined this action FAILS. You MUST narrate failure. "
                    f"The action does NOT succeed — it is blocked, dodged, countered, or backfires. "
                    f"Do NOT describe the player winning or achieving their goal.]\n\n"
                    f"{player_input}"
                )

            async for chunk in self._handle_narrative(
                outcome_injected_input,
                combat_outcome=outcome_value,
                combat_opponent_name=opponent_name,
                combat_npc_power=npc_power,
            ):
                yield chunk

            # Evaluate player power update after combat narrative
            if self._history:
                power_change = await self._evaluate_power_update(self._history[-1].get("content", ""), player_input)
                if power_change:
                    yield f"[POWER]{json.dumps(power_change)}"

            # Log combat as journal entry (supplement auto-detection)
            combat_summary = (
                f"Combat action: {player_input}. "
                f"Opponent: {opponent_name} (power {npc_power}). "
                f"Player power: {self._player_power}. "
                f"Outcome: {outcome_value}. Quality: {evaluation.final_quality}/10."
            )
            combat_entry = await self._journal.evaluate_and_log(self.campaign_id, combat_summary)
            if self._is_journal_entry(combat_entry):
                yield f"[JOURNAL]{json.dumps({'category': combat_entry.category.value, 'summary': combat_entry.summary, 'created_at': combat_entry.created_at})}"
        except Exception:
            logger.warning("Combat engine failed, falling back to narrative handling", exc_info=True)
            async for chunk in self._handle_narrative(player_input):
                yield chunk

    def _find_existing_node_id(self, name: str, name_to_id: dict[str, str]) -> str | None:
        """Find an existing node by exact match or alias/substring matching.

        Handles cases like a short name matching its full canonical form.
        Returns the node_id if found, None otherwise.
        """
        lower = name.lower()
        # Exact match
        if lower in name_to_id:
            return name_to_id[lower]
        # Check if the new name is a substring of an existing name, or vice versa
        for existing_name, node_id in name_to_id.items():
            if lower in existing_name or existing_name in lower:
                return node_id
        return None

    async def _extract_entities_to_graph(self, narrative_text: str):
        """Use LLM to extract entities and relationships from narrative, store in Neo4j."""
        # Build canonical name list from existing graph nodes + NPC minds
        canonical_names: list[str] = []
        try:
            existing_nodes = await self._graph.get_all_nodes()
            canonical_names = [n.name for n in existing_nodes]
        except Exception:
            pass
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                if mind.name not in canonical_names:
                    canonical_names.append(mind.name)

        name_hint = ""
        if canonical_names:
            names_str = ", ".join(canonical_names[:40])
            name_hint = (
                f"\n\nKNOWN ENTITIES (use these exact names when they appear in the text): "
                f"[{names_str}]. If the text mentions a short form, "
                f"match it to the full canonical name from this list."
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "Extract named entities and relationships from this RPG narrative. "
                    "Return ONLY valid JSON (no markdown): "
                    '{"entities": [{"name": str, "type": "NPC|LOCATION|FACTION|ITEM|EVENT", '
                    '"attributes": {}}], '
                    '"relationships": [{"source": str, "target": str, "rel_type": str}]}. '
                    "IMPORTANT: Always use the FULL canonical name for each entity. "
                    "Never abbreviate to just a first name or last name — use the complete name as it appears in the narrative. "
                    "For locations, use the most specific full name. "
                    "Only include entities explicitly named in the text. "
                    "rel_type should be a short verb phrase like GUARDS, LEADS, LOCATED_IN, OWNS, ALLIED_WITH, MET, KNOWS."
                    + name_hint
                ),
            },
            {"role": "user", "content": narrative_text},
        ]
        raw = await self._narrator._llm.complete(messages=messages, max_tokens=2048)
        data = parse_json_dict(raw)
        if not data:
            return

        from app.engines.graph_engine import WorldNodeType

        # Track name -> node_id for relationship creation
        name_to_id: dict[str, str] = {}

        # First, get existing nodes to avoid duplicates
        existing = await self._graph.get_all_nodes()
        for node in existing:
            name_to_id[node.name.lower()] = node.id

        for entity in data.get("entities", []):
            name = entity.get("name", "").strip()
            if not name:
                continue
            existing_id = self._find_existing_node_id(name, name_to_id)
            if existing_id:
                # Map this name variant to the existing node for relationship resolution
                name_to_id[name.lower()] = existing_id
                continue
            try:
                node_type = WorldNodeType(entity.get("type", "NPC"))
            except ValueError:
                node_type = WorldNodeType.NPC
            node = await self._graph.add_node(
                node_type=node_type,
                name=name,
                attributes=entity.get("attributes", {}),
            )
            name_to_id[name.lower()] = node.id

        for rel in data.get("relationships", []):
            source_name = rel.get("source", "").strip()
            target_name = rel.get("target", "").strip()
            rel_type = rel.get("rel_type", "RELATED_TO")
            source_id = self._find_existing_node_id(source_name, name_to_id)
            target_id = self._find_existing_node_id(target_name, name_to_id)
            if source_id and target_id and source_id != target_id:
                await self._graph.add_relationship(source_id, target_id, rel_type)

    @staticmethod
    def _build_combat_narrator_hint(
        outcome: str,
        opponent_name: str = "",
        opponent_power: int = 5,
        player_power: int = 3,
    ) -> str:
        """Build narrator instructions based on combat outcome and power levels.

        Uses the creativity-based combat system rules:
        - CRIT_SUCCESS: Spectacular success + 1 free action
        - SUCCESS: Action succeeds as intended
        - FAIL: Action fails, story continues
        - CRIT_FAIL: Action backfires — NPC gains +2 actions
        """
        power_ctx = (
            f"\nPOWER CONTEXT: Player power={player_power}/10, "
            f"Opponent '{opponent_name}' power={opponent_power}/10. "
        )
        if player_power > opponent_power + 2:
            power_ctx += "The player is significantly stronger — narrate accordingly (confident, controlled)."
        elif opponent_power > player_power + 2:
            power_ctx += "The opponent is significantly stronger — narrate the power gap (struggle, desperation)."
        else:
            power_ctx += "They are roughly matched — narrate a tense, balanced exchange."

        rules = {
            "CRIT_SUCCESS": (
                "\n\nCOMBAT RESULT — CRITICAL SUCCESS:\n"
                "The player's action was SPECTACULARLY successful. "
                "Narrate an impressive, cinematic success that exceeds expectations. "
                "The player earns 1 FREE BONUS ACTION after this — hint at this opportunity. "
                "Make the success feel earned and thrilling."
                + power_ctx
            ),
            "SUCCESS": (
                "\n\nCOMBAT RESULT — SUCCESS:\n"
                "The player's action SUCCEEDED as intended. "
                "Narrate the action landing effectively. The opponent is affected. "
                "Keep it grounded — success, not miraculous."
                + power_ctx
            ),
            "FAIL": (
                "\n\nCOMBAT RESULT — FAIL (MANDATORY — THIS OVERRIDES PLAYER INTENT):\n"
                "The player's action FAILED. The dice have spoken — no matter how well-described "
                "the player's action is, it DOES NOT SUCCEED.\n"
                "RULES YOU MUST FOLLOW:\n"
                "1. The action MUST miss, be blocked, dodged, countered, or interrupted.\n"
                "2. The opponent takes advantage of the failed attack.\n"
                "3. The player suffers a setback: takes damage, loses position, wastes energy, or gets disarmed.\n"
                "4. Do NOT let the player achieve ANY part of their stated goal.\n"
                "5. Narrate the failure creatively — show WHY it failed (opponent too fast, technique backfired, environment interfered).\n"
                "6. End with the player in a WORSE position than before the action.\n"
                "ABSOLUTELY DO NOT describe the player succeeding, winning, or achieving their objective."
                + power_ctx
            ),
            "CRIT_FAIL": (
                "\n\nCOMBAT RESULT — CRITICAL FAILURE:\n"
                "The player's action BACKFIRED catastrophically. This is MANDATORY. "
                "The action not only failed but caused harm or disadvantage to the player. "
                "The opponent gains +2 actions (a significant tactical advantage). "
                "Narrate the backfire dramatically — the player's own move used against them, "
                "a stumble that exposes a weakness, or an unintended consequence. "
                "DO NOT describe any success. The situation worsens for the player."
                + power_ctx
            ),
        }
        return rules.get(outcome, rules["FAIL"])

    @staticmethod
    def _is_response_complete(text: str) -> bool:
        """Check if the LLM response ends with complete sentence punctuation."""
        if not text:
            return True
        stripped = text.rstrip()
        if not stripped:
            return True
        return stripped[-1] in '.!?…"\u201d»)'

    @staticmethod
    def _fix_number_spacing(text: str) -> str:
        """Fix LLM output where numbers and words get glued together.

        Common patterns: 'Grau3' → 'Grau 3', 'às7h' → 'às 7h',
        'de5%' → 'de 5%', 'desde2005' → 'desde 2005', 'Vítima1' → 'Vítima 1',
        'suairmã' → 'sua irmã' (DeepSeek word concatenation).
        """
        import re
        # Fix numbered items FIRST (before general letter→digit spacing)
        # 'usadas2.' → 'usadas\n2.' and 'combate3)' → 'combate\n3)'
        text = re.sub(r'([a-zA-ZÀ-ÿ.,;:!?])(\d+[).](?:\s|$))', r'\1\n\2', text)
        # Fix list items glued: '- ' after word without newline
        text = re.sub(r'([a-zA-ZÀ-ÿ.,;:!?])- ([A-ZÀ-ÿ])', r'\1\n- \2', text)
        # Insert space between a letter (including accented) and a digit
        text = re.sub(r'([a-zA-ZÀ-ÿ])(\d)', r'\1 \2', text)
        # Insert space between a digit and an uppercase letter
        text = re.sub(r'(\d)([A-ZÀ-ÿ])', r'\1 \2', text)
        # Fix Portuguese word concatenation (DeepSeek artifact).
        # Only use 4+ letter prefixes to avoid false positives inside real words.
        # Short prefixes (de/do/na/no/em/um/nos/das) appear inside too many words.
        _PT_SAFE_PREFIXES = (
            r'(?:suas|seus|minha|meus|minhas|tuas|teus|'
            r'nossa|nosso|nossas|nossos|'
            r'pela|pelo|pelas|pelos|'
            r'aquela|aquele|'
            r'muito|pouco|outro|outra|outros|outras)'
        )
        # Require the glued suffix to be 3+ chars; prefix must not be preceded by a letter
        text = re.sub(
            rf'(?<![a-zA-ZÀ-ÿ])({_PT_SAFE_PREFIXES})([a-záàâãéèêíïóôõúüç]{{3,}})',
            lambda m: m.group(1) + ' ' + m.group(2),
            text,
        )
        return text

    @staticmethod
    def _clean_truncated_response(text: str) -> str:
        """If the response was cut mid-sentence by token limit, trim to the last complete sentence."""
        if not text:
            return text
        stripped = text.rstrip()
        # If it already ends with sentence-ending punctuation, it's fine
        if stripped and stripped[-1] in '.!?…"»)\u201d':
            return text
        # Find the last sentence-ending punctuation
        last_end = -1
        for i in range(len(stripped) - 1, -1, -1):
            if stripped[i] in '.!?…':
                last_end = i
                break
            # Also check for closing quote after punctuation (e.g. '."' or '!"')
            if stripped[i] in '"\u201d»)' and i > 0 and stripped[i - 1] in '.!?…':
                last_end = i
                break
        if last_end > 0 and last_end > len(stripped) * 0.5:
            # Only trim if we keep at least 50% of the text
            return stripped[:last_end + 1]
        return text

    @staticmethod
    def _extract_inventory_tags(text: str) -> tuple[str, list[dict]]:
        """Extract [ITEM_ADD/USE/LOSE] tags from text. Returns (clean_text, events)."""
        import re
        events = []
        for match in re.finditer(r'\[ITEM_ADD:([^|]+)\|([^|]+)\|([^\]]+)\]', text):
            events.append({"action": "add", "name": match.group(1).strip(), "category": match.group(2).strip(), "source": match.group(3).strip()})
        for match in re.finditer(r'\[ITEM_USE:([^\]]+)\]', text):
            events.append({"action": "use", "name": match.group(1).strip()})
        for match in re.finditer(r'\[ITEM_LOSE:([^\]]+)\]', text):
            events.append({"action": "lose", "name": match.group(1).strip()})
        clean = re.sub(r'\[ITEM_(?:ADD:[^\]]+|USE:[^\]]+|LOSE:[^\]]+)\]', '', text)
        return clean, events

    @staticmethod
    def _coerce_mode(mode: object) -> NarrativeMode:
        if isinstance(mode, NarrativeMode):
            return mode

        if isinstance(mode, str):
            normalized = mode.split(".")[-1].upper()
            try:
                return NarrativeMode(normalized)
            except ValueError:
                return NarrativeMode.NARRATIVE

        return NarrativeMode.NARRATIVE

    @staticmethod
    def _is_journal_entry(value: object) -> bool:
        try:
            from app.engines.journal_engine import JournalEntry
        except Exception:
            return False
        return isinstance(value, JournalEntry)
