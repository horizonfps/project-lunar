import logging
import os
from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings

from app.services.game_session import GameSession
from app.engines.narrator_engine import NarratorEngine
from app.engines.memory_engine import MemoryEngine, CrystalTier
from app.engines.world_reactor import WorldReactor
from app.engines.journal_engine import JournalEngine, JournalCategory
from app.engines.combat_engine import CombatEngine
from app.engines.plot_generator import PlotGenerator
from app.engines.npc_mind_engine import NpcMindEngine
from app.engines.inventory_engine import InventoryEngine
from app.engines.llm_router import LLMRouter, LLMConfig, LLMProvider, reset_call_log, get_call_summary
from app.engines.opening_generator import (
    format_setup_lines,
    generate_opening,
)
from app.db.event_store import EventStore, EventType
from app.db.scenario_store import ScenarioStore
from app.services.scenario_interpolation import interpolate

logger = logging.getLogger(__name__)

router = APIRouter()

# Ensure API keys from config are available in os.environ for litellm
if not os.environ.get("ANTHROPIC_API_KEY") and settings.anthropic_api_key:
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
if not os.environ.get("DEEPSEEK_API_KEY") and settings.deepseek_api_key:
    os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
if not os.environ.get("OPENAI_API_KEY") and settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_event_store = EventStore(os.environ.get("EVENT_DB_PATH", os.path.join(_BACKEND_DIR, "events.db")))
_llm = LLMRouter(LLMConfig())
_narrator = NarratorEngine(llm=_llm)
_memory = MemoryEngine(event_store=_event_store, llm=_llm)
_world_reactor = WorldReactor(llm=_llm)
_journal = JournalEngine(llm=_llm, event_store=_event_store)
_combat = CombatEngine(llm=_llm)
_plot_generator = PlotGenerator(llm=_llm)
_npc_minds = NpcMindEngine(llm=_llm)
_inventory = InventoryEngine(event_store=_event_store)

_sessions: dict[str, GameSession] = {}
_graph_engines: dict = {}

_SCENARIO_DB_PATH = os.environ.get(
    "SCENARIO_DB_PATH", os.path.join(_BACKEND_DIR, "scenarios.db")
)


def _load_story_cards_for_campaign(campaign_id: str):
    """Look up the scenario_id from the campaign and load its story cards."""
    try:
        store = ScenarioStore(_SCENARIO_DB_PATH)
        # Find the campaign's scenario_id
        conn = store._conn
        row = conn.execute(
            "SELECT scenario_id FROM campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        if not row:
            return []
        scenario_id = row[0]
        return store.get_story_cards(scenario_id)
    except Exception:
        logger.debug("Could not load story cards for campaign %s", campaign_id)
        return []


def _load_scenario_for_campaign(campaign_id: str):
    """Load scenario tone, language, and opening narrative for a campaign."""
    try:
        store = ScenarioStore(_SCENARIO_DB_PATH)
        conn = store._conn
        row = conn.execute(
            "SELECT s.tone_instructions, s.language, s.opening_narrative "
            "FROM scenarios s JOIN campaigns c ON c.scenario_id = s.id "
            "WHERE c.id=?",
            (campaign_id,),
        ).fetchone()
        if not row:
            return "", "en", ""
        return row[0] or "", row[1] or "en", row[2] or ""
    except Exception:
        logger.debug("Could not load scenario for campaign %s", campaign_id)
        return "", "en", ""


def _load_setup_answers_for_campaign(campaign_id: str) -> dict:
    """Load setup wizard answers persisted for the campaign (empty if none)."""
    try:
        with ScenarioStore(_SCENARIO_DB_PATH) as store:
            campaign = store.get_campaign(campaign_id)
        return campaign.setup_answers if campaign else {}
    except Exception:
        logger.debug("Could not load setup answers for campaign %s", campaign_id)
        return {}


def _ensure_session(campaign_id: str) -> GameSession:
    """Get or create a GameSession, ensuring all in-memory state is rebuilt.

    This is used by GET endpoints that need rebuilt data (NPC minds, journal,
    crystals, inventory) without requiring a player action first.
    """
    if campaign_id in _sessions:
        return _sessions[campaign_id]

    tone, language, opening = _load_scenario_for_campaign(campaign_id)
    story_cards = _load_story_cards_for_campaign(campaign_id)
    setup_answers = _load_setup_answers_for_campaign(campaign_id)
    combat_enabled = True
    # If the campaign has an AI-generated opening, prefer it over the
    # scenario template — that's the text the player saw in the UI.
    try:
        with ScenarioStore(_SCENARIO_DB_PATH) as _store:
            _campaign = _store.get_campaign(campaign_id)
        if _campaign:
            if _campaign.generated_opening:
                opening = _campaign.generated_opening
            combat_enabled = _campaign.combat_enabled
    except Exception:
        logger.debug("Could not load campaign metadata for %s", campaign_id)
    graph = _get_graph_engine(campaign_id)
    graphiti = _get_graphiti_engine()
    if graphiti:
        _memory.set_graphiti(graphiti)

    _sessions[campaign_id] = GameSession(
        campaign_id=campaign_id,
        scenario_tone=tone,
        language=language,
        narrator=_narrator,
        memory=_memory,
        world_reactor=_world_reactor,
        journal=_journal,
        event_store=_event_store,
        combat_engine=_combat,
        graph_engine=graph,
        npc_minds=_npc_minds,
        graphiti_engine=graphiti,
        plot_generator=_plot_generator,
        inventory_engine=_inventory,
        opening_narrative=opening,
        story_cards=story_cards,
        setup_answers=setup_answers,
        combat_enabled=combat_enabled,
    )
    return _sessions[campaign_id]

_graphiti_engine = None


def _get_graphiti_engine():
    global _graphiti_engine
    if _graphiti_engine is not None:
        return _graphiti_engine
    try:
        from app.engines.graphiti_engine import GraphitiEngine
        _graphiti_engine = GraphitiEngine(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        return _graphiti_engine
    except Exception:
        logger.info("Graphiti not available, running without temporal graph")
        return None


async def _fallback_graph_search(campaign_id: str, query: str, limit: int = 10) -> list[dict]:
    """Fallback keyword search over Neo4j world graph when Graphiti has no results."""
    graph = _get_graph_engine(campaign_id)
    if not graph:
        return []

    try:
        await graph.initialize()
        nodes = await graph.get_all_nodes()
        relationships = await graph.get_all_relationships()
    except Exception:
        logger.warning("Fallback world graph search failed for campaign %s", campaign_id, exc_info=True)
        return []

    term = query.strip().lower()
    if not term:
        return []

    node_lookup = {getattr(n, "id", ""): n for n in nodes}
    matched_nodes = []
    for node in nodes:
        name = str(getattr(node, "name", ""))
        attrs = getattr(node, "attributes", {}) or {}
        attr_text = " ".join(str(v) for v in attrs.values())
        haystack = f"{name} {attr_text}".lower()
        if term in haystack:
            matched_nodes.append(node)

    facts: list[dict] = []
    seen: set[str] = set()
    for node in matched_nodes:
        node_type = getattr(node, "node_type", None)
        node_type_value = node_type.value if hasattr(node_type, "value") else str(node_type or "NODE")
        node_fact = f"{getattr(node, 'name', 'Unknown')} [{node_type_value}]"
        if node_fact not in seen:
            facts.append({"fact": node_fact, "valid_at": None, "invalid_at": None})
            seen.add(node_fact)
            if len(facts) >= limit:
                break

        for rel in relationships:
            source = node_lookup.get(rel.get("source_id"))
            target = node_lookup.get(rel.get("target_id"))
            if not source or not target:
                continue
            if getattr(source, "id", None) != getattr(node, "id", None) and getattr(target, "id", None) != getattr(node, "id", None):
                continue

            rel_fact = (
                f"{getattr(source, 'name', 'Unknown')} "
                f"-{rel.get('rel_type', 'RELATED_TO')}-> "
                f"{getattr(target, 'name', 'Unknown')}"
            )
            if rel_fact in seen:
                continue

            facts.append({"fact": rel_fact, "valid_at": None, "invalid_at": None})
            seen.add(rel_fact)
            if len(facts) >= limit:
                break
        if len(facts) >= limit:
            break

    return facts[:limit]


class PlayerActionRequest(BaseModel):
    campaign_id: str = Field(..., min_length=1, max_length=64)
    scenario_tone: str = Field(default="", max_length=50000)
    language: str = Field(default="en", max_length=10)
    action: str = Field(..., min_length=1, max_length=20000)
    opening_narrative: str = Field(default="", max_length=50000)
    max_tokens: int = Field(default=2000, ge=256, le=8192)
    provider: str = Field(default="deepseek", max_length=20)
    model: str = Field(default="deepseek-v4-flash", max_length=64)
    temperature: float = Field(default=0.85, ge=0.0, le=2.0)
    combat_enabled: bool | None = None


class SettingsRequest(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.85
    max_tokens: int = 2000


class GenerateRequest(BaseModel):
    type: str  # "npc", "event", "plot"
    language: str = "en"


class TimeskipRequest(BaseModel):
    seconds: int


class NpcMindUpdateRequest(BaseModel):
    thoughts: dict[str, str]  # {thought_key: value}


class InventoryActionRequest(BaseModel):
    name: str
    action: str  # "use" or "discard"


class SetupAnswer(BaseModel):
    var_name: str
    resolved_prompt: str = ""
    type: str  # "text" | "choice"
    value: str
    description: str = ""


class SetupAnswersRequest(BaseModel):
    answers: dict[str, SetupAnswer]


class CampaignSettingsRequest(BaseModel):
    combat_enabled: bool


def _get_graph_engine(campaign_id: str):
    """Get or create a GraphEngine for the given campaign."""
    if campaign_id in _graph_engines:
        return _graph_engines[campaign_id]
    try:
        from app.engines.graph_engine import GraphEngine
        engine = GraphEngine(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, campaign_id)
        _graph_engines[campaign_id] = engine
        return engine
    except Exception:
        logger.info("GraphEngine not available for campaign %s", campaign_id)
        return None


@router.post("/action")
async def player_action(req: PlayerActionRequest):
    session = _ensure_session(req.campaign_id)
    # Update session with request-specific values that may differ per action.
    # The frontend may send the raw tone template — re-interpolate against the
    # session's setup answers so {var} tokens never reach the narrator.
    if req.scenario_tone:
        session.scenario_tone = interpolate(
            req.scenario_tone, session._setup_answers,
            context=f"campaign:{req.campaign_id}:tone",
        )
    session.language = req.language or session.language
    # Apply user's LLM settings per-request
    try:
        _llm.config.primary_provider = LLMProvider(req.provider)
    except ValueError:
        pass
    _llm.config.primary_model = req.model
    _llm.config.temperature = req.temperature
    _llm.config.max_tokens = req.max_tokens
    if req.combat_enabled is not None:
        session.set_combat_enabled(req.combat_enabled)

    async def event_stream():
        reset_call_log()
        async for chunk in session.process_action(req.action, max_tokens=req.max_tokens):
            # SSE requires each data line to be prefixed with "data:".
            # This preserves paragraph breaks/newlines in streamed prose.
            text = str(chunk).replace("\r\n", "\n").replace("\r", "\n")
            for line in text.split("\n"):
                yield f"data: {line}\n"
            yield "\n"
        summary = get_call_summary()
        logger.warning(
            "📊 ACTION COMPLETE: %d LLM calls, %d input tokens, %d output tokens, %.1fs total",
            summary["call_count"], summary["total_input_tokens"],
            summary["total_output_tokens"], summary["total_time_s"],
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{campaign_id}/scenario-view")
async def get_scenario_view(campaign_id: str):
    """Return the resolved per-campaign scenario surface (opening, tone, lore).

    Precedence for ``opening_narrative``:
      1. ``campaign.generated_opening`` if non-empty (AI-generated path).
      2. ``scenario.opening_narrative`` interpolated against setup_answers.
    """
    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        campaign = store.get_campaign(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        scenario = store.get_scenario(campaign.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    answers = campaign.setup_answers or {}
    ctx_root = f"campaign:{campaign_id}"
    opening = campaign.generated_opening or interpolate(
        scenario.opening_narrative, answers, context=f"{ctx_root}:opening",
    )
    return {
        "title": scenario.title,
        "language": scenario.language,
        "opening_narrative": opening,
        "tone_instructions": interpolate(
            scenario.tone_instructions, answers, context=f"{ctx_root}:tone",
        ),
        "lore_text": interpolate(
            scenario.lore_text, answers, context=f"{ctx_root}:lore",
        ),
        "opening_mode": scenario.opening_mode,
        "has_generated_opening": bool(campaign.generated_opening),
        "combat_enabled": campaign.combat_enabled,
    }


@router.get("/{campaign_id}/setup-state")
async def get_setup_state(campaign_id: str):
    """Return the wizard state for a campaign: questions defined by the scenario,
    answers already saved, and whether the wizard still needs to run."""
    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        campaign = store.get_campaign(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        scenario = store.get_scenario(campaign.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    questions = scenario.setup_questions or []
    answers = campaign.setup_answers or {}
    needs_setup = bool(questions) and not answers
    return {
        "questions": questions,
        "answers": answers,
        "needs_setup": needs_setup,
    }


async def _maybe_generate_opening(
    campaign_id: str,
    setup_payload: dict,
) -> str | None:
    """If the scenario opts into AI openings, generate one and persist it.

    Returns the generated text on success, ``None`` if the scenario is in
    fixed mode or generation failed (the caller falls back to the static
    template). Any LLM failure is logged but never raised — players should
    not be blocked by an outage at session start.
    """
    import time

    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        campaign = store.get_campaign(campaign_id)
        if not campaign:
            return None
        scenario = store.get_scenario(campaign.scenario_id)
    if not scenario or scenario.opening_mode != "ai":
        return None

    lines = format_setup_lines(setup_payload, scenario.setup_questions)
    router_ = LLMRouter(LLMConfig())
    t0 = time.monotonic()
    try:
        text = await generate_opening(
            language=scenario.language,
            tone=scenario.tone_instructions,
            lore=scenario.lore_text,
            character_setup_lines=lines,
            director_note=scenario.ai_opening_directive,
            router=router_,
        )
    except Exception:
        logger.exception(
            "AI opening generation failed for campaign %s — falling back to template",
            campaign_id,
        )
        return None

    duration_ms = int((time.monotonic() - t0) * 1000)
    if not text:
        return None

    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        store.update_generated_opening(campaign_id, text)

    try:
        _event_store.append(
            campaign_id=campaign_id,
            event_type=EventType.AI_OPENING_GENERATED,
            payload={
                "char_count": len(text),
                "model": router_.config.primary_model,
                "duration_ms": duration_ms,
            },
            narrative_time_delta=0,
            location="meta",
            entities=[],
        )
    except Exception:
        logger.debug("Could not log AI_OPENING_GENERATED event", exc_info=True)
    return text


@router.patch("/{campaign_id}/settings")
async def update_campaign_settings(campaign_id: str, req: CampaignSettingsRequest):
    """Persist campaign-level toggles (e.g. combat mode on/off)."""
    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        ok = store.update_combat_enabled(campaign_id, req.combat_enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Campaign not found")
    session = _sessions.get(campaign_id)
    if session:
        session.set_combat_enabled(req.combat_enabled)
    return {"status": "ok", "combat_enabled": req.combat_enabled}


@router.post("/{campaign_id}/setup-answers")
async def save_setup_answers(campaign_id: str, req: SetupAnswersRequest):
    """Persist the wizard answers and refresh the active session so the
    CHARACTER SETUP block is injected on the next action."""
    payload = {k: v.model_dump() for k, v in req.answers.items()}
    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        ok = store.update_setup_answers(campaign_id, payload)
    if not ok:
        raise HTTPException(status_code=404, detail="Campaign not found")

    generated = await _maybe_generate_opening(campaign_id, payload)

    # Drop the cached session so _ensure_session re-reads setup_answers next call.
    _sessions.pop(campaign_id, None)
    return {
        "status": "ok",
        "answers": payload,
        "generated_opening": generated or "",
    }


@router.post("/{campaign_id}/regenerate-opening")
async def regenerate_opening(campaign_id: str):
    """Re-roll the AI-generated opening for an as-yet-untouched campaign.

    Locked once any narrator turn exists for the campaign — re-rolling the
    opening mid-story would break the AI's history continuity.
    """
    with ScenarioStore(_SCENARIO_DB_PATH) as store:
        campaign = store.get_campaign(campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        scenario = store.get_scenario(campaign.scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if scenario.opening_mode != "ai":
        raise HTTPException(
            status_code=400,
            detail="Scenario is not in AI opening mode.",
        )

    existing = _event_store.get_by_type(campaign_id, EventType.NARRATOR_RESPONSE)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Cannot re-roll the opening after the story has begun.",
        )

    generated = await _maybe_generate_opening(campaign_id, campaign.setup_answers or {})
    if not generated:
        raise HTTPException(
            status_code=502,
            detail="Opening generation failed. Try again or check API keys.",
        )

    # Drop the cached session so the new opening seeds the next history rebuild.
    _sessions.pop(campaign_id, None)
    return {"status": "ok", "opening_narrative": generated}


@router.get("/{campaign_id}/history")
async def get_history(campaign_id: str):
    """Return PLAYER_ACTION and NARRATOR_RESPONSE events to rebuild chat UI."""
    events = _event_store.get_by_type(campaign_id, EventType.PLAYER_ACTION) + \
             _event_store.get_by_type(campaign_id, EventType.NARRATOR_RESPONSE)
    events.sort(key=lambda e: e.created_at)
    messages = []
    for ev in events:
        text = ev.payload.get("text", "")
        if ev.event_type == EventType.PLAYER_ACTION:
            messages.append({"role": "user", "content": text})
        else:
            messages.append({"role": "assistant", "content": text})
    return {"messages": messages}


@router.post("/{campaign_id}/rewind")
async def rewind(campaign_id: str):
    """Delete the last player action + AI response and return updated history."""
    deleted = _event_store.delete_last_pair(campaign_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="No actions to rewind")

    # If there's a live session, rewind its in-memory state
    if campaign_id in _sessions:
        _sessions[campaign_id].rewind()

    # Return updated message history (same format as GET /history)
    events = _event_store.get_by_type(campaign_id, EventType.PLAYER_ACTION) + \
             _event_store.get_by_type(campaign_id, EventType.NARRATOR_RESPONSE)
    events.sort(key=lambda e: e.created_at)
    messages = []
    for ev in events:
        text = ev.payload.get("text", "")
        if ev.event_type == EventType.PLAYER_ACTION:
            messages.append({"role": "user", "content": text})
        else:
            messages.append({"role": "assistant", "content": text})
    return {"messages": messages, "deleted": deleted}


@router.get("/{campaign_id}/journal")
async def get_journal(campaign_id: str, category: str | None = None):
    _ensure_session(campaign_id)
    if category:
        try:
            cat = JournalCategory(category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid journal category: {category}")
        entries = _journal.get_by_category(campaign_id, cat)
    else:
        entries = _journal.get_journal(campaign_id)
    return [asdict(e) for e in entries]


@router.get("/{campaign_id}/npc-minds")
async def get_npc_minds(campaign_id: str):
    _ensure_session(campaign_id)
    minds = _npc_minds.get_all_minds(campaign_id)
    return [m.to_dict() for m in minds]


@router.delete("/{campaign_id}/npc-minds/{npc_name}")
async def delete_npc_mind(campaign_id: str, npc_name: str):
    """Delete an NPC mind from memory and event store."""
    _ensure_session(campaign_id)
    deleted = _npc_minds.delete_mind(campaign_id, npc_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"NPC '{npc_name}' not found")
    _event_store.delete_npc_thoughts(campaign_id, npc_name)
    return {"status": "deleted", "name": npc_name}


@router.put("/{campaign_id}/npc-minds/{npc_name}")
async def update_npc_mind(campaign_id: str, npc_name: str, req: NpcMindUpdateRequest):
    """Update thoughts for an NPC mind."""
    _ensure_session(campaign_id)
    mind = None
    for key, value in req.thoughts.items():
        mind = _npc_minds.update_thought(campaign_id, npc_name, key, value)
    if not mind:
        raise HTTPException(status_code=404, detail=f"NPC '{npc_name}' not found")
    # Persist updated thoughts to event store
    thoughts_dict = {k: t.value for k, t in mind.thoughts.items()}
    _event_store.upsert_npc_thought(campaign_id, mind.name, thoughts_dict, mind.aliases)
    return mind.to_dict()


@router.get("/{campaign_id}/characters")
async def get_characters(campaign_id: str, q: str = ""):
    """List all known characters/entities for @-mention autocomplete.

    Returns NPCs from NpcMindEngine + entities from GraphEngine (if available).
    Optional query parameter `q` filters by substring match.
    """
    _ensure_session(campaign_id)
    characters: list[dict] = []
    seen_names: set[str] = set()

    # NPCs from mind engine (primary source — has thoughts and aliases)
    for mind in _npc_minds.get_all_minds(campaign_id):
        name_lower = mind.name.lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)
        characters.append({
            "name": mind.name,
            "aliases": mind.aliases,
            "type": "NPC",
        })

    # Entities from graph engine (if available)
    session = _sessions.get(campaign_id)
    if session and hasattr(session, "_graph") and session._graph:
        try:
            nodes = await session._graph.get_all_nodes()
            for node in nodes:
                name_lower = node.name.lower()
                if name_lower in seen_names:
                    continue
                seen_names.add(name_lower)
                characters.append({
                    "name": node.name,
                    "aliases": [],
                    "type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
                })
        except Exception:
            pass

    # Filter by query if provided
    if q:
        q_lower = q.lower()
        characters = [
            c for c in characters
            if q_lower in c["name"].lower()
            or any(q_lower in a.lower() for a in c.get("aliases", []))
        ]

    return characters


@router.get("/{campaign_id}/memory-crystals")
async def get_memory_crystals(campaign_id: str):
    _ensure_session(campaign_id)
    crystals = _memory.get_crystals(campaign_id)
    return [
        {
            "tier": c.tier.value,
            "content": c.content,
            "event_count": c.event_count,
        }
        for c in crystals
    ]


@router.post("/{campaign_id}/crystallize")
async def crystallize_memory(campaign_id: str):
    crystal = await _memory.crystallize(campaign_id, CrystalTier.SHORT)
    return {
        "tier": crystal.tier.value,
        "content": crystal.content,
        "event_count": crystal.event_count,
    }


@router.post("/{campaign_id}/generate")
async def generate_content(campaign_id: str, req: GenerateRequest):
    world_ctx = _memory.build_context_window(campaign_id)
    if req.type == "npc":
        npc = await _plot_generator.generate_npc(world_ctx, language=req.language)
        return asdict(npc)
    elif req.type == "event":
        total_time = _event_store.get_total_narrative_time(campaign_id)
        event = await _plot_generator.generate_random_event("current", world_ctx, total_time, language=req.language)
        return asdict(event)
    elif req.type == "plot":
        arc = await _plot_generator.generate_plot_arc(world_ctx, language=req.language)
        return {"text": arc}
    return {"error": "Unknown type"}


@router.post("/{campaign_id}/inject-npc-seed")
async def inject_npc_seed(campaign_id: str, req: GenerateRequest):
    """Generate an NPC and inject it as a pending seed in the active session."""
    if campaign_id not in _sessions:
        raise HTTPException(404, "No active session for this campaign")
    session = _sessions[campaign_id]
    world_ctx = _memory.build_context_window(campaign_id)
    existing_names = []
    if session._npc_minds:
        existing_names = [m.name for m in session._npc_minds.get_all_minds(campaign_id)]
    npc = await _plot_generator.generate_npc(
        world_ctx, language=req.language, existing_npc_names=existing_names,
    )
    from dataclasses import asdict as _asdict
    npc_data = _asdict(npc)
    session._pending_npc_seed = npc_data
    session._pending_npc_introduced = False
    return {"status": "injected", "npc": npc_data}


@router.post("/{campaign_id}/timeskip")
async def timeskip(campaign_id: str, req: TimeskipRequest):
    _event_store.append(
        campaign_id=campaign_id,
        event_type=EventType.TIMESKIP,
        payload={"seconds": req.seconds},
        narrative_time_delta=req.seconds,
        location="world",
        entities=[],
    )
    world_ctx = _memory.build_context_window(campaign_id)
    session_language = _sessions[campaign_id].language if campaign_id in _sessions else "en"
    world_changes = await _world_reactor.process_tick(
        campaign_id=campaign_id,
        narrative_seconds=req.seconds,
        world_context=world_ctx,
        language=session_language,
    )
    if world_changes:
        _event_store.append(
            campaign_id=campaign_id,
            event_type=EventType.WORLD_TICK,
            payload={"text": world_changes},
            narrative_time_delta=0,
            location="world",
            entities=[],
        )
        try:
            await _journal.evaluate_and_log(campaign_id, world_changes)
        except Exception:
            logger.warning("Failed to log timeskip world changes into journal", exc_info=True)
    return {"summary": world_changes or "Time passes quietly."}


@router.get("/{campaign_id}/inventory")
async def get_inventory(campaign_id: str):
    _ensure_session(campaign_id)
    items = _inventory.get_inventory(campaign_id)
    return [{"name": i.name, "category": i.category, "source": i.source, "status": i.status} for i in items]


@router.post("/{campaign_id}/inventory")
async def update_inventory(campaign_id: str, req: InventoryActionRequest):
    if req.action == "use":
        _inventory.use_item(campaign_id, req.name)
    elif req.action == "discard":
        _inventory.lose_item(campaign_id, req.name)
    return {"status": "ok"}


@router.get("/{campaign_id}/graph-search")
async def graph_search(campaign_id: str, q: str = ""):
    if not q:
        return {"facts": []}

    facts: list[dict] = []
    engine = _get_graphiti_engine()
    if engine:
        facts = await engine.search(campaign_id, q)

    if not facts:
        facts = await _fallback_graph_search(campaign_id, q)

    return {"facts": facts}


@router.get("/{campaign_id}/world-graph")
async def get_world_graph(campaign_id: str):
    try:
        engine = _get_graph_engine(campaign_id)
        if not engine:
            return {"nodes": [], "links": []}
        await engine.initialize()
        nodes = await engine.get_all_nodes()
        rels = await engine.get_all_relationships()
        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "node_type": n.node_type.value,
                    "attributes": n.attributes,
                }
                for n in nodes
            ],
            "links": [
                {
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "rel_type": r["rel_type"],
                    "strength": r["strength"],
                }
                for r in rels
            ],
        }
    except Exception as e:
        logger.warning("Failed to fetch world graph for campaign %s: %s", campaign_id, e)
        return {"nodes": [], "links": []}
