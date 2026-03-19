from __future__ import annotations
import json
import logging
from dataclasses import asdict
from typing import AsyncIterator

from app.db.event_store import EventStore, EventType
from app.engines.narrator_engine import NarrativeMode
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
    ):
        self.campaign_id = campaign_id
        self.scenario_tone = scenario_tone
        self.language = language
        self._narrator = narrator
        self._memory = memory
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

        # Rebuild conversation history from persisted events so the AI
        # has full context even after a server restart or new session.
        self._rebuild_history_from_events()
        self._rebuild_npc_minds_from_events()

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

    async def process_action(self, player_input: str, max_tokens: int = 2000) -> AsyncIterator[str]:
        self._max_tokens = max_tokens
        mode, meta = await self._narrator.detect_mode(player_input)
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

    async def _handle_narrative(self, player_input: str, mode: NarrativeMode = NarrativeMode.NARRATIVE) -> AsyncIterator[str]:
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
            system_prompt = self._narrator.build_system_prompt(
                tone_instructions=self.scenario_tone,
                memory_context=memory_ctx,
                language=self.language,
                inventory_context=inventory_ctx,
                max_tokens=getattr(self, '_max_tokens', 2000),
            )

        # Stream narrative from LLM
        full_response = ""
        async for chunk in self._narrator.stream_narrative(
            player_input, system_prompt, self._history
        ):
            full_response += chunk
            yield chunk

        # Clean truncation: if the response was cut mid-sentence by token limit,
        # trim to the last complete sentence so there's no dangling text.
        full_response = self._clean_truncated_response(full_response)

        # Process inventory tags from response
        clean_response = full_response
        if self._inventory:
            clean_response, inv_events = self._extract_inventory_tags(full_response)
            for inv_event in inv_events:
                self._apply_inventory_event(inv_event)
                yield f"[INVENTORY]{json.dumps(inv_event)}"

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
        """Run all post-narrative side effects: NPC minds, graph, memory, graphiti."""
        await self._update_npc_minds(clean_response)
        await self._extract_to_graph(clean_response)

        crystal = await self._try_auto_crystallize()
        if crystal:
            yield f"[CRYSTAL]{json.dumps({'tier': crystal.tier.value, 'event_count': crystal.event_count})}"

        await self._ingest_to_graphiti(clean_response, "narrator_response")

    async def _update_npc_minds(self, narrative_text: str) -> None:
        if not self._npc_minds or not narrative_text:
            return
        try:
            if self._graphiti:
                world_ctx = await self._memory.build_context_window_async(self.campaign_id)
            else:
                world_ctx = self._memory.build_context_window(self.campaign_id)
            updated = await self._npc_minds.update_npc_thoughts(
                campaign_id=self.campaign_id,
                narrative_text=narrative_text,
                world_context=world_ctx,
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
            logger.warning("NPC mind update failed", exc_info=True)

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

        safe_context = world_context or "(no context yet)"
        total_narrative_time = self._event_store.get_total_narrative_time(self.campaign_id)

        # Only one auto-trigger per turn to avoid noisy output.
        for kind in ("plot_arc", "npc", "event"):
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

            payload: dict
            if kind == "npc":
                npc = await self._plot_generator.generate_npc(safe_context)
                payload = {"kind": kind, "source": "auto", "data": asdict(npc)}
            elif kind == "event":
                event = await self._plot_generator.generate_random_event(
                    location="current",
                    world_context=safe_context,
                    narrative_time=total_narrative_time,
                )
                payload = {"kind": kind, "source": "auto", "data": asdict(event)}
            else:
                arc = await self._plot_generator.generate_plot_arc(safe_context)
                payload = {"kind": kind, "source": "auto", "data": {"text": arc}}

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

            yield f"[PLOT_AUTO]{json.dumps(payload, ensure_ascii=False)}"
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

            npc_power = 5  # default; GraphEngine provides real value when available
            evaluation = await self._combat.evaluate_action(
                action=player_input,
                npc_name="opponent",
                npc_power=npc_power,
            )
            outcome = self._combat.roll_outcome(evaluation.final_quality, npc_power)
            outcome_value = outcome.value if hasattr(outcome, "value") else str(outcome)

            self._event_store.append(
                campaign_id=self.campaign_id,
                event_type=EventType.COMBAT_RESULT,
                payload={"outcome": outcome_value, "quality": evaluation.final_quality},
                narrative_time_delta=0,
                location="current",
                entities=["player"],
            )

            # Prepend outcome hint for narrator
            outcome_hint = f"[Combat outcome: {outcome_value}] "
            yield outcome_hint

            async for chunk in self._handle_narrative(player_input):
                yield chunk

            # Log combat as journal entry (supplement auto-detection)
            combat_summary = (
                f"Combat action: {player_input}. "
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

        Handles cases like 'Gojo' matching 'Satoru Gojo', or 'Megumi' matching
        'Megumi Fushiguro'. Returns the node_id if found, None otherwise.
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
                    "For example, use 'Satoru Gojo' not just 'Gojo', "
                    "'Megumi Fushiguro' not just 'Megumi', "
                    "'Nobara Kugisaki' not just 'Nobara'. "
                    "For locations, use the most specific full name. "
                    "Only include entities explicitly named in the text. "
                    "rel_type should be a short verb phrase like GUARDS, LEADS, LOCATED_IN, OWNS, ALLIED_WITH."
                ),
            },
            {"role": "user", "content": narrative_text},
        ]
        raw = await self._narrator._llm.complete(messages=messages)
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
