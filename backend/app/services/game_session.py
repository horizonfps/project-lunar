from __future__ import annotations
import asyncio
import json
import logging
import os
from dataclasses import asdict
from typing import AsyncIterator

from app.db.event_store import EventStore, EventType
from app.engines.llm_router import LLMProvider
from app.engines.narrator_engine import NarrativeMode, estimate_tokens
from app.engines.plot_generator import AUTO_PLOT_RULES
from app.services.scenario_interpolation import interpolate
from app.utils.json_parsing import parse_json_dict

logger = logging.getLogger(__name__)


def _perspective_filter_enabled() -> bool:
    """Camada 3 feature flag — defaults ON.

    Set LUNAR_FEATURE_PERSPECTIVE_FILTER=0/false to disable witness
    extraction and per-NPC filtering entirely. When off, all events keep
    empty witnessed_by lists and the NPC mind / narrator pipelines fall
    back to their pre-Camada-3 (omniscient) behavior.
    """
    raw = os.environ.get("LUNAR_FEATURE_PERSPECTIVE_FILTER", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _npc_decay_enabled() -> bool:
    """Camada 4 feature flag — defaults ON.

    Set LUNAR_FEATURE_NPC_DECAY=0/false to disable transient-thought decay,
    the factual/narrative context split, and personality-anchor injection.
    When off, the NPC mind pipeline falls back to its pre-Camada-4
    (single context, thoughts never expire) behavior.
    """
    raw = os.environ.get("LUNAR_FEATURE_NPC_DECAY", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


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
        setup_answers: dict | None = None,
        combat_enabled: bool = True,
    ):
        self.campaign_id = campaign_id
        self.language = language
        self._setup_answers = setup_answers or {}
        self._combat_enabled = bool(combat_enabled)
        # Tone may reference {var} placeholders that draw from setup_answers
        # — resolve them once now so the narrator never sees raw template tokens.
        self.scenario_tone = interpolate(
            scenario_tone, self._setup_answers,
            context=f"campaign:{campaign_id}:tone",
        )
        self._character_setup_block = self._build_character_setup_block()
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
        # Known opponent power levels — persisted from previous combats
        self._known_opponent_powers: dict[str, int] = {}

        # Rebuild conversation history from persisted events so the AI
        # has full context even after a server restart or new session.
        self._rebuild_history_from_events()
        self._rebuild_npc_minds_from_events()
        self._rebuild_plot_lock_from_events()
        self._rebuild_journal_from_events()
        self._rebuild_memory_crystals()
        self._rebuild_player_power()
        self._rebuild_known_opponent_powers()

        # Resolve the opening once and keep it on the session so it can be
        # injected into every system prompt as canonical context (preventing
        # the narrator from substituting opening NPCs with similarly-described
        # canonical alternatives from story cards).
        self._opening_narrative = interpolate(
            opening_narrative, self._setup_answers,
            context=f"campaign:{campaign_id}:opening",
        ) if opening_narrative else ""

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

    def _serialize_thoughts(self, mind) -> dict:
        """Camada 4 — persist value plus decay metadata so timing survives restarts."""
        out: dict[str, dict] = {}
        for k, t in mind.thoughts.items():
            out[k] = {
                "value": t.value,
                "created_at_turn": t.created_at_turn,
                "decay_after_turns": t.decay_after_turns,
            }
        return out

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
        # Reconstruct minds — accept both legacy (str value) and Camada-4
        # (dict with value + decay metadata) thought shapes.
        for name, payload in latest_per_npc.items():
            mind = self._npc_minds._ensure_mind(self.campaign_id, name)
            for alias in payload.get("aliases", []):
                if alias.lower() not in [a.lower() for a in mind.aliases]:
                    mind.aliases.append(alias)
            for key, raw in payload.get("thoughts", {}).items():
                if isinstance(raw, dict):
                    value = raw.get("value")
                    if not value:
                        continue
                    mind.set_thought(
                        key,
                        str(value),
                        current_turn=int(raw.get("created_at_turn", 0) or 0),
                        decay_after_turns=raw.get("decay_after_turns"),
                    )
                elif raw:
                    mind.set_thought(key, str(raw))
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
        self._rebuild_player_power()
        self._rebuild_known_opponent_powers()

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
                # Prefer the row-level witnessed_by (set on row insert);
                # fall back to payload for forward-compat with rows whose
                # witnessed_by lives only in the JSON blob.
                witnesses = list(ev.witnessed_by or ev.payload.get("witnessed_by", []))
                entries.append(JournalEntry(
                    campaign_id=self.campaign_id,
                    category=category,
                    summary=ev.payload.get("summary", ""),
                    created_at=ev.created_at,
                    witnessed_by=witnesses,
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
        """Rebuild memory crystals from MEMORY_CRYSTAL events in the store.

        Handles the pyramid system: SHORT, MEDIUM, LONG, MEMORY tiers.
        Consumed state is INFERRED from tier counts (the DB payload is unreliable
        because consumed is only updated in-memory during consolidation).
        The cursor tracks the last SHORT crystal's timestamp for uncrystallized events.
        """
        from app.engines.memory_engine import MemoryCrystal, CrystalTier
        crystal_events = self._event_store.get_by_type(
            self.campaign_id, EventType.MEMORY_CRYSTAL,
        )
        crystals = []
        for ev in crystal_events:
            try:
                tier_str = ev.payload.get("tier", "SHORT")
                # Handle old "LONG" crystals from before the pyramid system
                # by mapping them to MEDIUM (closest equivalent)
                if tier_str == "LONG" and "consumed" not in ev.payload:
                    tier_str = "MEDIUM"
                tier = CrystalTier(tier_str)
                # witnessed_by may live in the payload (newer crystals) or be
                # missing entirely (legacy crystals from before Camada 3).
                # Missing → empty list, which means "not witnessed by anyone"
                # — safe default that excludes the crystal from per-NPC views.
                witnesses = list(ev.payload.get("witnessed_by", []))
                crystals.append(MemoryCrystal(
                    campaign_id=self.campaign_id,
                    tier=tier,
                    content=ev.payload.get("summary", ""),
                    ai_content=ev.payload.get("ai_content", ""),
                    event_count=ev.payload.get("event_count", 0),
                    consumed=False,  # Inferred below from tier counts
                    source_start_created_at=None,
                    source_end_created_at=ev.created_at,
                    witnessed_by=witnesses,
                ))
            except Exception:
                continue

        # Infer consumed state from tier counts.
        # Each higher-tier crystal was created by consuming CONSOLIDATION_COUNT
        # crystals of the previous tier (oldest first, in creation order).
        consolidation_count = self._memory.CONSOLIDATION_COUNT
        for current_tier in (CrystalTier.SHORT, CrystalTier.MEDIUM, CrystalTier.LONG):
            next_tier = current_tier.next_tier
            if next_tier is None:
                continue
            next_count = sum(1 for c in crystals if c.tier == next_tier)
            consumed_count = next_count * consolidation_count
            current_tier_crystals = [c for c in crystals if c.tier == current_tier]
            for c in current_tier_crystals[:consumed_count]:
                c.consumed = True

        self._memory._crystals[self.campaign_id] = crystals
        # Cursor = last SHORT crystal's timestamp (for uncrystallized event tracking)
        short_crystals = [c for c in crystals if c.tier == CrystalTier.SHORT]
        if short_crystals:
            self._memory._last_crystal_cursor[self.campaign_id] = short_crystals[-1].source_end_created_at
        else:
            self._memory._last_crystal_cursor.pop(self.campaign_id, None)

    def _build_power_scale_reference(self) -> str:
        """Build a power scale reference from NPC story cards.

        Uses the existing NPC power_level values as calibration anchors.
        No hardcoded progression system — the scale comes entirely from the scenario data.
        """
        npc_powers = []
        for card in self._story_cards:
            if hasattr(card, 'card_type') and getattr(card.card_type, 'value', str(card.card_type)).upper() == "NPC":
                content = card.content if isinstance(card.content, dict) else {}
                power = content.get("power_level")
                if power is not None:
                    npc_powers.append((card.name, int(power)))
        if not npc_powers:
            return ""
        npc_powers.sort(key=lambda x: x[1], reverse=True)
        # Include both ends of the scale — top AND bottom anchors
        # so the LLM sees what "strong" and "weak" look like in this world.
        if len(npc_powers) <= 50:
            selected = npc_powers
        else:
            top = npc_powers[:25]
            bottom = npc_powers[-25:]
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

    def _build_character_setup_block(self) -> str:
        """Format setup_answers into a CHARACTER SETUP block injected into the
        narrator's system prompt. Returns empty string when no answers exist."""
        if not self._setup_answers:
            return ""
        lines: list[str] = ["CHARACTER SETUP (locked from session start):"]
        for answer in self._setup_answers.values():
            if not isinstance(answer, dict):
                continue
            var_name = answer.get("var_name") or ""
            value = answer.get("value") or ""
            description = answer.get("description") or ""
            if not var_name or not value:
                continue
            lines.append(f"- {var_name}: {value}")
            if description:
                lines.append(f"  {description}")
        if len(lines) == 1:  # only the header
            return ""
        return "\n".join(lines)

    def _init_player_power(self) -> int:
        """Sync default — overridden by _rebuild_player_power or _ensure_player_power."""
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
        self._player_power_initialized = len(events) > 0

    def _rebuild_known_opponent_powers(self) -> None:
        """Rebuild known opponent power levels from COMBAT_RESULT events."""
        self._known_opponent_powers.clear()
        combat_events = self._event_store.get_by_type(
            self.campaign_id, EventType.COMBAT_RESULT,
        )
        for ev in combat_events:
            name = ev.payload.get("opponent_name", "")
            power = ev.payload.get("opponent_power")
            if name and power is not None:
                self._known_opponent_powers[name.lower()] = int(power)

    def set_combat_enabled(self, enabled: bool) -> None:
        self._combat_enabled = bool(enabled)

    @property
    def combat_enabled(self) -> bool:
        return self._combat_enabled

    async def _ensure_player_power(self) -> None:
        """If player power was never evaluated, run a full-context LLM analysis.

        Uses scenario tone, story cards (NPC power scale), and conversation
        history to determine where the player currently sits on the power scale.
        Only runs once — persists the result as a POWER_LEVEL_UPDATE event.
        """
        if getattr(self, '_player_power_initialized', False):
            return
        if not self._combat:
            self._player_power_initialized = True
            return

        power_scale = self._build_power_scale_reference()
        if not power_scale:
            self._player_power_initialized = True
            return

        # Build story summary using the same dynamic budget as the narrator
        history_summary = ""
        if self._history:
            context_window = self._get_context_window()
            system_overhead = estimate_tokens(power_scale) + estimate_tokens(self.scenario_tone or "") + 500
            output_reserve = 500  # small response (just JSON)
            budget = context_window - system_overhead - output_reserve
            parts: list[str] = []
            used = 0
            for msg in reversed(self._history):
                content = msg.get("content", "")
                line = f"[{msg.get('role', '?')}] {content}"
                line_tokens = estimate_tokens(line)
                if used + line_tokens > budget:
                    break
                parts.append(line)
                used += line_tokens
            parts.reverse()
            history_summary = "\n".join(parts)

        messages = [
            {
                "role": "system",
                "content": (
                    "Analyze the player character's current power level based on the world context. "
                    "Return ONLY JSON: {\"power\": int, \"reason\": str}. "
                    "power must be 0-10, calibrated against the NPC power scale below.\n\n"
                    + power_scale
                    + "\n\nSCENARIO CONTEXT:\n" + (self.scenario_tone or "")[:8000]
                ),
            },
            {
                "role": "user",
                "content": (
                    "Based on the world power scale above and the story so far, "
                    "what is the player character's current power level?\n\n"
                    "RECENT STORY:\n" + (history_summary or "(new campaign, no history yet)")
                ),
            },
        ]
        try:
            logger.info(
                "_ensure_player_power: running for campaign %s (history=%d msgs, scale=%d chars)",
                self.campaign_id, len(self._history), len(power_scale),
            )
            raw = await self._combat._llm.complete(messages=messages, max_tokens=128)
            logger.info("_ensure_player_power: LLM response: %s", (raw or "")[:200])
            data = parse_json_dict(raw)
            if data and "power" in data:
                new_power = max(0, min(10, int(data["power"])))
                reason = str(data.get("reason", "initial evaluation"))
                self._player_power = new_power
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.POWER_LEVEL_UPDATE,
                    payload={
                        "target": "player",
                        "old_power": 3,
                        "new_power": new_power,
                        "reason": reason,
                    },
                    narrative_time_delta=0,
                    location="current",
                    entities=["player"],
                )
                logger.info("Initial player power evaluated: %d (%s)", new_power, reason)
            else:
                logger.warning("_ensure_player_power: LLM returned no 'power' key. data=%s", data)
        except Exception:
            logger.warning("Initial player power evaluation failed", exc_info=True)
        self._player_power_initialized = True

    def _resolve_opponent_power(self, opponent_name: str, llm_estimate: int) -> int:
        """Resolve opponent power with priority: story cards > previous combats > LLM estimate."""
        if not opponent_name:
            return llm_estimate

        name_lower = opponent_name.lower()

        # 1. Check story cards (named NPCs with defined power)
        for card in self._story_cards:
            if hasattr(card, 'card_type') and getattr(card.card_type, 'value', str(card.card_type)).upper() == "NPC":
                if card.name.lower() == name_lower or name_lower in card.name.lower():
                    power = card.content.get("power_level", llm_estimate) if isinstance(card.content, dict) else llm_estimate
                    return max(1, min(10, int(power)))

        # 2. Check previous combats (same or similar opponent type)
        if name_lower in self._known_opponent_powers:
            return self._known_opponent_powers[name_lower]
        # Fuzzy: check if any known opponent name contains or is contained by this name
        for known_name, known_power in self._known_opponent_powers.items():
            if known_name in name_lower or name_lower in known_name:
                return known_power

        # 3. Fall back to LLM estimate
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
                    f"Narrative result: {narrative[:8000]}"
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
    _STORY_CARDS_MAX_BUDGET = 200_000     # ceiling sized for 1M context window
    _STORY_CARDS_MAX_COUNT = 300          # hard cap on number of cards regardless of budget

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
                mind.set_thought("feeling", npc.get("personality", "observing"), current_turn=self._turn_count)
                mind.set_thought("goal", npc.get("goal", "unknown"), current_turn=self._turn_count)
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.NPC_THOUGHT,
                    payload={
                        "name": mind.name,
                        "thoughts": self._serialize_thoughts(mind),
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

        # Ensure player power is evaluated with full context (runs once per campaign)
        await self._ensure_player_power()

        # Single-call mode for Anthropic: one LLM call does everything
        if self._is_single_call_provider():
            async for chunk in self._process_action_single_call(player_input, max_tokens):
                yield chunk
            return

        story_ctx = self._history[-1]["content"] if self._history else ""
        power_scale = self._build_power_scale_reference()
        if power_scale:
            story_ctx += "\n" + power_scale
        mode, meta = await self._narrator.detect_mode(player_input, story_context=story_ctx)
        mode = self._coerce_mode(mode)
        if mode == NarrativeMode.COMBAT and not self._combat_enabled:
            mode = NarrativeMode.NARRATIVE
        narrative_time = meta.get("narrative_time_seconds", 60)
        if mode != NarrativeMode.META:
            self._turn_count += 1

        player_event = self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.PLAYER_ACTION,
            payload={"text": player_input, "mode": mode.value},
            narrative_time_delta=narrative_time,
            location="current",
            entities=["player"],
        )
        # Tracked so _async_side_effects can stamp witnesses onto this turn's
        # PLAYER_ACTION + NARRATOR_RESPONSE events after extraction.
        self._last_player_event_id = player_event.id
        self._last_narrator_event_id = ""

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

        # World reactor and auto-plot run async (fire-and-forget)
        if mode != NarrativeMode.META:
            asyncio.create_task(self._async_world_tick(narrative_time))

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
        # RAG inputs for crystal selection: scene query + active NPC names.
        recent_narrative = self._history[-1]["content"] if self._history else ""
        rag_query = f"{player_input}\n{recent_narrative}"
        active_npc_names: set[str] = set()
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                active_npc_names.add(mind.name)
        rag_context_window = self._get_context_window()

        if self._graphiti:
            memory_ctx = await self._memory.build_context_window_async(
                self.campaign_id,
                query_text=rag_query,
                active_npc_names=active_npc_names,
                context_window=rag_context_window,
            )
        else:
            memory_ctx = self._memory.build_context_window(
                self.campaign_id,
                query_text=rag_query,
                active_npc_names=active_npc_names,
                context_window=rag_context_window,
            )

        # Gather world context (shared by all modes)
        inventory_ctx = ""
        if self._inventory:
            inventory_ctx = self._inventory.format_for_prompt(self.campaign_id)

        graph_ctx = await self.get_graph_relationship_summary()

        npc_ctx = self._format_npc_states_context()

        journal_ctx = ""
        if self._journal:
            try:
                entries = self._journal.get_journal(self.campaign_id)
                if entries:
                    lines = ["STORY LOG (key events so far):"]
                    for e in entries[-40:]:
                        lines.append(f"- {e.summary}")
                    journal_ctx = "\n".join(lines)
            except Exception:
                pass

        story_cards_ctx = self._format_story_cards_context(
            player_input=player_input,
            recent_narrative=self._history[-1]["content"] if self._history else "",
        )

        if mode == NarrativeMode.META:
            system_prompt = self._narrator.build_meta_prompt(
                language=self.language,
                memory_context=memory_ctx,
                inventory_context=inventory_ctx,
                journal_context=journal_ctx,
                npc_context=npc_ctx,
                graph_context=graph_ctx,
                story_cards_context=story_cards_ctx,
            )
        else:
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

            # Camada 3 — append per-NPC knowledge boundaries so the narrator
            # writes NPC dialogue / actions consistent with what each NPC
            # could actually know.
            knowledge_block = self._build_npc_knowledge_boundaries_block(active_npc_names)
            if knowledge_block:
                narrator_hints += knowledge_block

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
                story_cards_context=story_cards_ctx,
                character_setup=self._character_setup_block,
                opening_narrative=self._opening_narrative,
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
                "then end at a natural pause point. Keep the same tone and language. "
                "STRICT: do NOT take any new actions, decisions, dialogue or "
                "internal thoughts on the player's behalf. If the previous text "
                "already ended at or near a question/prompt directed at the player, "
                "just close the current sentence cleanly and stop — do NOT introduce "
                "new beats, NPC reactions to imagined player actions, or further "
                "narrative progression."
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
        narrator_event = self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.NARRATOR_RESPONSE,
            payload={"text": clean_response},
            narrative_time_delta=0,
            location="current",
            entities=[],
        )
        self._last_narrator_event_id = narrator_event.id

        # Fire side-effects async (non-blocking) — journal, NPC minds, graph,
        # crystallization, power update all run after the narrative is sent.
        if mode != NarrativeMode.META and clean_response:
            asyncio.create_task(self._async_side_effects(clean_response))
        else:
            # META mode: only journal (lightweight)
            asyncio.create_task(self._async_journal(clean_response))

    async def _process_action_single_call(self, player_input: str, max_tokens: int) -> AsyncIterator[str]:
        """Single LLM call mode for Anthropic: narrative + mode + NPCs + entities in one request."""
        # Detect mode first so combat pipeline runs before the main LLM call
        story_ctx = self._history[-1]["content"] if self._history else ""
        power_scale = self._build_power_scale_reference()
        if power_scale:
            story_ctx += "\n" + power_scale
        mode, meta = await self._narrator.detect_mode(player_input, story_context=story_ctx)
        mode = self._coerce_mode(mode)
        if mode == NarrativeMode.COMBAT and not self._combat_enabled:
            mode = NarrativeMode.NARRATIVE
        narrative_time = meta.get("narrative_time_seconds", 60)
        if mode != NarrativeMode.META:
            self._turn_count += 1

        # Persist player action (same as streaming path)
        player_event = self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.PLAYER_ACTION,
            payload={"text": player_input, "mode": mode.value},
            narrative_time_delta=narrative_time,
            location="current",
            entities=["player"],
        )
        self._last_player_event_id = player_event.id
        self._last_narrator_event_id = ""

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
                llm_estimate = meta.get("opponent_power", 3)
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
                if combat_opponent_name:
                    self._known_opponent_powers[combat_opponent_name.lower()] = combat_npc_power

                yield (
                    f"[Combat: {combat_opponent_name} (power {combat_npc_power}) "
                    f"vs Player (power {self._player_power}) → {combat_outcome}] "
                )
            except Exception:
                logger.warning("Combat engine failed in single-call path", exc_info=True)

        # Build context (same as _handle_narrative) — pass RAG query so crystals
        # are ranked by relevance to the current scene instead of mere recency.
        recent_narrative = self._history[-1]["content"] if self._history else ""
        rag_query = f"{player_input}\n{recent_narrative}"
        active_npc_names: set[str] = set()
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                active_npc_names.add(mind.name)
        rag_context_window = self._get_context_window()

        if self._graphiti:
            memory_ctx = await self._memory.build_context_window_async(
                self.campaign_id,
                query_text=rag_query,
                active_npc_names=active_npc_names,
                context_window=rag_context_window,
            )
        else:
            memory_ctx = self._memory.build_context_window(
                self.campaign_id,
                query_text=rag_query,
                active_npc_names=active_npc_names,
                context_window=rag_context_window,
            )

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

        # Camada 3 — append NPC knowledge boundaries (mirrors streaming path).
        knowledge_block = self._build_npc_knowledge_boundaries_block(active_npc_names)
        if knowledge_block:
            narrator_hints += knowledge_block

        graph_ctx = await self.get_graph_relationship_summary()

        npc_ctx = self._format_npc_states_context()

        journal_ctx = ""
        if self._journal:
            try:
                entries = self._journal.get_journal(self.campaign_id)
                if entries:
                    lines = ["STORY LOG (key events so far):"]
                    for e in entries[-40:]:
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
                recent_narrative=self._history[-1]["content"] if self._history else "",
            ),
            character_setup=self._character_setup_block,
            opening_narrative=self._opening_narrative,
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
                "then end at a natural pause point. Keep the same tone and language. "
                "STRICT: do NOT take any new actions, decisions, dialogue or "
                "internal thoughts on the player's behalf. If the previous text "
                "already ended at or near a question/prompt directed at the player, "
                "just close the current sentence cleanly and stop — do NOT introduce "
                "new beats, NPC reactions to imagined player actions, or further "
                "narrative progression."
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
        narrator_event = self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.NARRATOR_RESPONSE,
            payload={"text": clean_response},
            narrative_time_delta=0,
            location="current",
            entities=[],
        )
        self._last_narrator_event_id = narrator_event.id

        # Camada 3 — extract witnesses synchronously here so the journal
        # evaluation (which runs immediately below) and the auto-crystallize
        # below pick up the perspective-stamped events.
        witnesses = await self._extract_witnesses(clean_response)
        self._apply_witnesses_to_recent_turn(witnesses)

        # Journal evaluation for narrative
        entry = await self._journal.evaluate_and_log(
            self.campaign_id, clean_response,
            language=self.language,
            witnessed_by=witnesses,
        )
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
            combat_entry = await self._journal.evaluate_and_log(self.campaign_id, combat_summary, language=self.language)
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
                                mind.set_thought(key, str(value), current_turn=self._turn_count)
                        self._event_store.append(
                            campaign_id=self.campaign_id,
                            event_type=EventType.NPC_THOUGHT,
                            payload={
                                "name": mind.name,
                                "thoughts": self._serialize_thoughts(mind),
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

    # ── Camada 3 — witness extraction (perspective filter) ─────────

    async def _extract_witnesses(self, narrative_text: str) -> list[str]:
        """Run a small LLM call to extract NPCs physically present in the scene.

        Returns the list of NPC names that the model judged to be in the same
        physical location as the player and able to see / hear what just
        happened. Excludes the player. Excludes NPCs that are merely
        remembered, mentioned, or referenced from elsewhere.

        Returns an empty list when the feature flag is off, when the LLM
        fails, or when the scene has no other characters present.
        """
        if not _perspective_filter_enabled():
            return []
        if not narrative_text:
            return []

        # Anchor the model on canonical names so it doesn't invent new ones
        # for characters that already exist in the campaign. We pull from
        # NPC minds (active in this campaign) and NPC story cards.
        candidates: list[str] = []
        seen_lower: set[str] = set()
        if self._npc_minds:
            for mind in self._npc_minds.get_all_minds(self.campaign_id):
                key = mind.name.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    candidates.append(mind.name)
        for card in self._story_cards:
            ct = getattr(card, "card_type", None)
            ct_val = ct.value if hasattr(ct, "value") else str(ct)
            if ct_val.upper() == "NPC":
                key = card.name.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    candidates.append(card.name)

        candidates_hint = ""
        if candidates:
            candidates_hint = (
                "\n\nKNOWN NPC NAMES (use these EXACT names when any of these "
                "characters are present — do not invent new spellings): "
                + ", ".join(candidates[:60])
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You analyze a single RPG scene and identify which NPCs are "
                    "PHYSICALLY PRESENT in the scene with the player. "
                    "An NPC is 'physically present' only if they are in the same "
                    "location as the player and could plausibly see or hear the "
                    "events being narrated. "
                    "EXCLUDE: the player; NPCs only mentioned in dialogue, "
                    "memories, flashbacks, or third-party reports; NPCs in another "
                    "place; abstract entities (factions, deities, generic crowds). "
                    "Return ONLY valid JSON (no markdown): "
                    '{"npcs_present": ["FullName1", "FullName2"]}. '
                    "Use full canonical names when available. If nobody is "
                    "present besides the player, return an empty list."
                    + candidates_hint
                ),
            },
            {"role": "user", "content": narrative_text},
        ]
        try:
            raw = await self._narrator._llm.complete(messages=messages, max_tokens=256)
            data = parse_json_dict(raw) or {}
            names = data.get("npcs_present", [])
            if not isinstance(names, list):
                return []
            cleaned: list[str] = []
            seen: set[str] = set()
            for n in names:
                if not isinstance(n, str):
                    continue
                name = n.strip().lstrip("@").strip()
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                cleaned.append(name)
            logger.info(
                "Witness extraction for campaign %s — npcs_present=%s",
                self.campaign_id, cleaned,
            )
            return cleaned
        except Exception:
            logger.warning("Witness extraction failed", exc_info=True)
            return []

    def _apply_witnesses_to_recent_turn(self, witnesses: list[str]) -> None:
        """Stamp the just-appended PLAYER_ACTION + NARRATOR_RESPONSE rows
        with the witness list so downstream consumers (journal,
        crystallization, perspective filter) read the right value.
        """
        if not witnesses:
            return
        for event_id in (self._last_player_event_id, self._last_narrator_event_id):
            if not event_id:
                continue
            try:
                self._event_store.update_witnessed_by(event_id, witnesses)
            except Exception:
                logger.warning(
                    "Failed to update witnessed_by for event %s", event_id,
                    exc_info=True,
                )

    async def _async_side_effects(self, clean_response: str) -> None:
        """Fire-and-forget side effects that run after the narrative is sent to the player.

        These are important for game state but don't need to block the SSE response.
        Any errors are logged but never surface to the player.
        """
        try:
            logger.info("_async_side_effects: starting (response %d chars)", len(clean_response))

            # Camada 3 — perspective filter. Run FIRST so every downstream
            # side-effect (journal, NPC mind update, crystallization) sees
            # the witnessed_by stamp on this turn's PLAYER_ACTION /
            # NARRATOR_RESPONSE events.
            witnesses = await self._extract_witnesses(clean_response)
            self._apply_witnesses_to_recent_turn(witnesses)

            # Journal evaluation (lightweight LLM call)
            await self._async_journal(clean_response, witnessed_by=witnesses)

            # NPC mind updates — restricted to NPCs actually present in scene.
            await self._update_npc_minds(clean_response, npcs_present=witnesses)

            # Graph entity extraction
            await self._extract_to_graph(clean_response)

            # Memory crystallization (may cascade to higher tiers).
            # Runs after witness stamping so source events carry the right
            # witnessed_by — the consolidation step takes the union.
            await self._try_auto_crystallize()

            # Graphiti ingestion
            await self._ingest_to_graphiti(clean_response, "narrator_response")

            # Power level evaluation
            last_player_input = ""
            if len(self._history) >= 2:
                last_player_input = self._history[-2].get("content", "")
            await self._evaluate_power_update(clean_response, last_player_input)

            logger.info("_async_side_effects: completed")
        except Exception:
            logger.error("_async_side_effects failed", exc_info=True)

    async def _async_world_tick(self, narrative_time: int) -> None:
        """Fire-and-forget world reactor tick + auto-plot generation."""
        try:
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

            # Auto-plot (still uses yields internally but we consume them here)
            async for _ in self._maybe_trigger_auto_plot(world_ctx):
                pass  # Plot events are persisted in _maybe_trigger_auto_plot
        except Exception:
            logger.error("_async_world_tick failed", exc_info=True)

    async def _async_journal(
        self,
        clean_response: str,
        witnessed_by: list[str] | None = None,
    ) -> None:
        """Fire-and-forget journal evaluation."""
        try:
            await self._journal.evaluate_and_log(
                self.campaign_id, clean_response,
                language=self.language,
                witnessed_by=witnessed_by,
            )
        except Exception:
            logger.warning("Async journal evaluation failed", exc_info=True)

    async def _post_narrative_pipeline(self, clean_response: str) -> AsyncIterator[str]:
        """Run all post-narrative side effects: NPC minds, graph, memory, graphiti, power.

        Legacy method — used by the single-call path which still yields signals inline.
        The streaming path uses _async_side_effects instead (fire-and-forget).
        """
        logger.info("_post_narrative_pipeline: starting (response %d chars)", len(clean_response))
        await self._update_npc_minds(clean_response)
        await self._extract_to_graph(clean_response)

        crystal = await self._try_auto_crystallize()
        if crystal:
            yield f"[CRYSTAL]{json.dumps({'tier': crystal.tier.value, 'event_count': crystal.event_count})}"

        await self._ingest_to_graphiti(clean_response, "narrator_response")

        last_player_input = ""
        if len(self._history) >= 2:
            last_player_input = self._history[-2].get("content", "")
        power_change = await self._evaluate_power_update(clean_response, last_player_input)
        if power_change:
            yield f"[POWER]{json.dumps(power_change)}"

    def _format_npc_states_context(self) -> str:
        """Build the NPC STATES context block, applying Camada 4 decay first.

        Drops expired transient thoughts based on `self._turn_count`, renders
        each NPC's current thoughts as `key=value` pairs, and (when decay is
        enabled) inlines per-NPC personality anchors so the narrator stays
        anchored in the NPC's identity.
        """
        if not self._npc_minds:
            return ""
        if _npc_decay_enabled():
            dropped = self._npc_minds.apply_decay_all(self.campaign_id, self._turn_count)
            if dropped:
                logger.info(
                    "Camada 4 decay dropped thoughts at turn %d: %s",
                    self._turn_count, dropped,
                )
        minds = self._npc_minds.get_all_minds(self.campaign_id)
        if not minds:
            return ""
        anchors_by_name = (
            self._build_personality_anchors([m.name for m in minds])
            if _npc_decay_enabled() else {}
        )
        lines = ["NPC STATES (what each NPC is currently thinking/feeling):"]
        for m in minds:
            thoughts = ", ".join(f"{k}={t.value}" for k, t in m.thoughts.items())
            lines.append(f"- {m.name}: {thoughts}")
            anchor = anchors_by_name.get(m.name)
            if anchor:
                anchor_inline = anchor.replace("\n", " | ").strip()
                lines.append(f"    anchors: {anchor_inline}")
        return "\n".join(lines)

    def _build_personality_anchors(self, npc_names: list[str] | None = None) -> dict[str, str]:
        """Camada 4 — collect personality anchors for the requested NPCs.

        An NPC story card may carry an optional `personality_anchors` dict in
        its content (e.g. `{"core_trait": "...", "speech_pattern": "...",
        "do_not_drift_to": "..."}`). This helper returns those anchors keyed
        by NPC name, formatted as a multi-line block per NPC. Cards without
        anchors are omitted; the result may be empty.

        When `npc_names` is provided, only anchors for those NPCs are
        returned. When None, anchors for every NPC card in the scenario are
        returned (used by NPC STATES context).
        """
        if not self._story_cards:
            return {}
        wanted: set[str] | None = None
        if npc_names is not None:
            wanted = {n.strip().lower() for n in npc_names if isinstance(n, str) and n.strip()}
        out: dict[str, str] = {}
        for card in self._story_cards:
            ct = getattr(card, "card_type", None)
            ct_val = ct.value if hasattr(ct, "value") else str(ct)
            if ct_val != "NPC":
                continue
            content = card.content if isinstance(card.content, dict) else {}
            anchors = content.get("personality_anchors")
            if not isinstance(anchors, dict) or not anchors:
                continue
            name = (card.name or "").strip()
            if not name:
                continue
            if wanted is not None and name.lower() not in wanted:
                continue
            lines: list[str] = []
            for k, v in anchors.items():
                if v is None:
                    continue
                lines.append(f"  {k}: {v}")
            if lines:
                out[name] = "\n".join(lines)
        return out

    def _build_factual_context(self) -> str:
        """Camada 4 — build the immutable canon block for NPC mind prompts.

        Combines MEMORY tier crystals (canonical world facts), the player
        inventory (canonical item facts), and a brief setup-answer summary
        when present. Excludes any narrator-mutable scene description so the
        LLM cannot rewrite canon to fit a single scene's flavor.
        """
        sections: list[str] = []

        # MEMORY tier crystals are canon. Re-use memory_engine's projection
        # but strip out the mutable LONG/MEDIUM/SHORT/DELTA tiers — we want
        # only the permanent facts.
        try:
            crystals = self._memory._crystals.get(self.campaign_id, [])
            from app.engines.memory_engine import CrystalTier
            memory_lines: list[str] = []
            for c in crystals:
                if c.tier == CrystalTier.MEMORY:
                    memory_lines.append(c.ai_content)
            if memory_lines:
                sections.append("=== PRMNT_MEM (canon) ===\n" + "\n".join(memory_lines))
        except Exception:
            logger.debug("Failed to extract MEMORY tier crystals for factual context", exc_info=True)

        if self._inventory:
            inv = self._inventory.format_for_prompt(self.campaign_id)
            if inv and inv.strip():
                sections.append(inv.strip())

        return "\n\n".join(sections)

    def _format_story_cards_for_npc(self, npc_name: str) -> str:
        """Return story cards visible to a specific NPC.

        Camada 3 — story cards may declare an optional `known_by` list in
        their content dict. When present, only NPCs in that list (or NPCs
        whose card name matches the card itself) treat the card as known
        knowledge. When absent, the card is public — every NPC may
        reference it (default behavior, scenario-agnostic).
        """
        if not npc_name or not self._story_cards:
            return ""
        npc_lower = npc_name.strip().lower()
        lines: list[str] = []
        for card in self._story_cards:
            content = card.content if isinstance(card.content, dict) else {}
            known_by = content.get("known_by")
            if isinstance(known_by, list) and known_by:
                allowed = {str(n).strip().lower() for n in known_by if isinstance(n, str)}
                # An NPC always knows their own card.
                if card.name.strip().lower() == npc_lower:
                    pass
                elif npc_lower not in allowed:
                    continue
            ct = getattr(card, "card_type", None)
            ct_val = ct.value if hasattr(ct, "value") else str(ct)
            parts = [f"[{ct_val}] {card.name}"]
            for k, v in content.items():
                if k == "known_by":
                    continue
                if v:
                    parts.append(f"  {k}: {v}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _build_npc_knowledge_boundaries_block(
        self,
        active_npc_names: set[str],
    ) -> str:
        """Build a NARRATOR-facing knowledge-boundary block for the system prompt.

        For each active NPC in the scene, lists what that NPC could plausibly
        know — canonical world facts (MEMORY tier) plus any past scenes the
        NPC actually witnessed. The narrator stays omniscient for general
        narration, but uses this block to constrain dialogue: NPC X's lines
        and actions must not reference facts X could not know.

        Returns empty string when the perspective filter is off or no
        active NPC has any knowledge to bound.
        """
        if not _perspective_filter_enabled() or not active_npc_names:
            return ""

        sections: list[str] = []
        for name in sorted(active_npc_names):
            if not name:
                continue
            crystal_knowledge = self._memory.build_npc_knowledge_window(self.campaign_id, name)
            card_knowledge = self._format_story_cards_for_npc(name)
            combined_parts: list[str] = []
            if crystal_knowledge:
                combined_parts.append(crystal_knowledge)
            if card_knowledge:
                combined_parts.append("=== STORY CARDS (accessible) ===\n" + card_knowledge)
            if combined_parts:
                sections.append(f"\n--- {name} knows ---\n" + "\n".join(combined_parts))

        if not sections:
            return ""

        return (
            "\nNPC KNOWLEDGE BOUNDARIES (CRITICAL — restricts what each NPC can "
            "reference in dialogue / inner thought; the narrator itself stays "
            "omniscient): when writing dialogue or actions for an NPC listed "
            "below, that NPC may ONLY reference the facts under their own "
            "section. They may NOT mention facts from other NPCs' sections, "
            "from scenes they did not witness, or about player details they "
            "never observed."
            + "".join(sections)
        )

    async def _update_npc_minds(
        self,
        narrative_text: str,
        npcs_present: list[str] | None = None,
    ) -> None:
        if not self._npc_minds or not narrative_text:
            logger.warning("_update_npc_minds skipped: npc_minds=%s, narrative_len=%d",
                           bool(self._npc_minds), len(narrative_text) if narrative_text else 0)
            return
        logger.info("_update_npc_minds: starting for campaign %s (narrative %d chars, present=%s)",
                    self.campaign_id, len(narrative_text), npcs_present or [])
        try:
            if self._graphiti:
                world_ctx = await self._memory.build_context_window_async(self.campaign_id)
            else:
                world_ctx = self._memory.build_context_window(self.campaign_id)
            # Last ~20 messages give the NPC mind enough live context to
            # remember relationships, deals, and identities established
            # outside the crystal pyramid's reach (crystals drop conversational
            # specifics during compression).
            recent_history = self._history[-20:] if self._history else []

            # Camada 3 — build per-NPC knowledge windows from witnessed
            # crystals + canon + accessible story cards. Falls back to
            # omniscient world_ctx for the general scene description.
            npc_knowledge: dict[str, str] = {}
            if _perspective_filter_enabled() and npcs_present:
                for name in npcs_present:
                    if not isinstance(name, str) or not name.strip():
                        continue
                    crystal_knowledge = self._memory.build_npc_knowledge_window(
                        self.campaign_id, name,
                    )
                    card_knowledge = self._format_story_cards_for_npc(name)
                    parts: list[str] = []
                    if crystal_knowledge:
                        parts.append(crystal_knowledge)
                    if card_knowledge:
                        parts.append("=== STORY CARDS (accessible) ===\n" + card_knowledge)
                    if parts:
                        npc_knowledge[name] = "\n".join(parts)

            # Camada 4 — split immutable canon from mutable scene context and
            # surface per-NPC personality anchors so the model anchors thought
            # generation in stable identity rather than fresh narrative flavor.
            factual_ctx = ""
            anchors: dict[str, str] = {}
            if _npc_decay_enabled():
                factual_ctx = self._build_factual_context()
                anchor_targets = npcs_present if npcs_present else None
                anchors = self._build_personality_anchors(anchor_targets)

            updated = await self._npc_minds.update_npc_thoughts(
                campaign_id=self.campaign_id,
                narrative_text=narrative_text,
                world_context=world_ctx,
                language=self.language,
                recent_history=recent_history,
                npcs_present=npcs_present,
                npc_knowledge=npc_knowledge,
                factual_context=factual_ctx,
                personality_anchors=anchors,
                current_turn=self._turn_count,
            )
            # Persist NPC thoughts so they survive server restarts
            for mind in updated:
                self._event_store.append(
                    campaign_id=self.campaign_id,
                    event_type=EventType.NPC_THOUGHT,
                    payload={
                        "name": mind.name,
                        "thoughts": self._serialize_thoughts(mind),
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
            return await self._memory.auto_crystallize_if_needed(self.campaign_id, language=self.language)
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
                recent_narrative = msg["content"][:8000]
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
            llm_estimate = meta.get("opponent_power", 3)
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
            if opponent_name:
                self._known_opponent_powers[opponent_name.lower()] = npc_power

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
            combat_entry = await self._journal.evaluate_and_log(self.campaign_id, combat_summary, language=self.language)
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
        opponent_power: int = 3,
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
        """Check if the LLM response ends with complete sentence punctuation.

        Trailing markdown emphasis (``*``/``_``/backticks) and whitespace are
        stripped before inspecting the final character. Without this, a
        properly closed ``**question?**`` is mistaken for a truncated
        response and triggers an unnecessary continuation pass — during
        which the LLM tends to ignore the just-asked question and narrate
        further actions on the player's behalf.
        """
        if not text:
            return True
        stripped = text.rstrip(" \t\r\n*_`")
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
