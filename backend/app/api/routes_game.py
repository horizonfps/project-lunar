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
from app.engines.llm_router import LLMRouter, LLMConfig, LLMProvider
from app.db.event_store import EventStore, EventType
from app.db.scenario_store import ScenarioStore

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
    scenario_tone: str = Field(default="", max_length=10000)
    language: str = Field(default="en", max_length=10)
    action: str = Field(..., min_length=1, max_length=10000)
    opening_narrative: str = Field(default="", max_length=20000)
    max_tokens: int = Field(default=2000, ge=256, le=8192)


class SettingsRequest(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: float = 0.85
    max_tokens: int = 2000


class GenerateRequest(BaseModel):
    type: str  # "npc", "event", "plot"
    language: str = "en"


class TimeskipRequest(BaseModel):
    seconds: int


class InventoryActionRequest(BaseModel):
    name: str
    action: str  # "use" or "discard"


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
    if req.campaign_id not in _sessions:
        graphiti = _get_graphiti_engine()
        if graphiti:
            _memory.set_graphiti(graphiti)
        graph = _get_graph_engine(req.campaign_id)
        if graph:
            try:
                await graph.initialize()
            except Exception:
                logger.warning("GraphEngine initialization failed", exc_info=True)
                graph = None
        story_cards = _load_story_cards_for_campaign(req.campaign_id)
        _sessions[req.campaign_id] = GameSession(
            campaign_id=req.campaign_id,
            scenario_tone=req.scenario_tone,
            language=req.language,
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
            opening_narrative=req.opening_narrative,
            story_cards=story_cards,
        )

    session = _sessions[req.campaign_id]
    # Apply user's max_tokens setting to the LLM router
    _llm.config.max_tokens = req.max_tokens

    async def event_stream():
        async for chunk in session.process_action(req.action, max_tokens=req.max_tokens):
            # SSE requires each data line to be prefixed with "data:".
            # This preserves paragraph breaks/newlines in streamed prose.
            text = str(chunk).replace("\r\n", "\n").replace("\r", "\n")
            for line in text.split("\n"):
                yield f"data: {line}\n"
            yield "\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    minds = _npc_minds.get_all_minds(campaign_id)
    return [m.to_dict() for m in minds]


@router.get("/{campaign_id}/characters")
async def get_characters(campaign_id: str, q: str = ""):
    """List all known characters/entities for @-mention autocomplete.

    Returns NPCs from NpcMindEngine + entities from GraphEngine (if available).
    Optional query parameter `q` filters by substring match.
    """
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
