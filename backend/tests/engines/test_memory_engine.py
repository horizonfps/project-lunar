import pytest
import json
from unittest.mock import AsyncMock
from app.engines.memory_engine import MemoryEngine, MemoryCrystal, CrystalTier
from app.db.event_store import EventStore, EventType


@pytest.fixture
def event_store(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    yield store
    store.close()


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps(
            {
                "ai_memory": "AI::compressed::memory",
                "player_summary": "Compressed memory crystal content.",
            }
        )
    )
    return llm


@pytest.fixture
def memory_engine(event_store, mock_llm):
    return MemoryEngine(event_store=event_store, llm=mock_llm)


def test_raw_context_returns_recent_events(memory_engine, event_store):
    for i in range(5):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])
    ctx = memory_engine.get_raw_context("c1", limit=3)
    assert len(ctx) == 3


@pytest.mark.asyncio
async def test_crystallize_creates_crystal(memory_engine, event_store):
    for i in range(5):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])
    crystal = await memory_engine.crystallize("c1", tier=CrystalTier.SHORT)
    assert crystal.content == "Compressed memory crystal content."
    assert crystal.ai_content == "AI::compressed::memory"
    assert crystal.tier == CrystalTier.SHORT
    assert crystal.campaign_id == "c1"


def test_build_context_window_includes_raw_events(memory_engine, event_store):
    event_store.append("c1", EventType.PLAYER_ACTION, {"text": "I enter the tavern"}, 60, "loc", [])
    context = memory_engine.build_context_window("c1")
    assert "I enter the tavern" in context


@pytest.mark.asyncio
async def test_build_context_window_includes_crystals(memory_engine, event_store):
    for i in range(5):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"event {i}"}, 60, "loc", [])
    await memory_engine.crystallize("c1", tier=CrystalTier.LONG)
    context = memory_engine.build_context_window("c1")
    assert "AI::compressed::memory" in context


def test_get_crystals_empty_for_new_campaign(memory_engine):
    crystals = memory_engine.get_crystals("new-campaign")
    assert crystals == []


@pytest.mark.asyncio
async def test_build_context_window_includes_graphiti_facts(event_store, mock_llm):
    mock_graphiti = AsyncMock()
    mock_graphiti.search = AsyncMock(return_value=[
        {"fact": "The knight betrayed the king in chapter 3.", "valid_at": None, "invalid_at": None},
        {"fact": "The goblin camp is north of the river.", "valid_at": None, "invalid_at": None},
    ])
    engine = MemoryEngine(event_store=event_store, llm=mock_llm, graphiti_engine=mock_graphiti)
    event_store.append("camp-1", EventType.PLAYER_ACTION, {"text": "I scout the northern road"}, 60, "loc", [])
    ctx = await engine.build_context_window_async("camp-1")
    assert "WORLD FACTS" in ctx
    assert "knight betrayed the king" in ctx
    assert "goblin camp" in ctx


@pytest.mark.asyncio
async def test_auto_crystallize_uses_fallback_when_llm_fails(event_store):
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("llm unavailable"))
    engine = MemoryEngine(event_store=event_store, llm=llm)

    for i in range(engine.AUTO_CRYSTALLIZE_THRESHOLD + 1):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])

    crystal = await engine.auto_crystallize_if_needed("c1")
    assert crystal is not None
    assert crystal.tier == CrystalTier.SHORT
    assert "action" in crystal.content.lower()


@pytest.mark.asyncio
async def test_auto_crystallize_is_incremental_without_repeating_events(event_store):
    llm = AsyncMock()
    llm.complete = AsyncMock(
        side_effect=[
            json.dumps({"ai_memory": "AI_DELTA_1", "player_summary": "summary-1"}),
            json.dumps({"ai_memory": "AI_DELTA_2", "player_summary": "summary-2"}),
        ]
    )
    engine = MemoryEngine(event_store=event_store, llm=llm)

    for i in range(engine.AUTO_CRYSTALLIZE_THRESHOLD):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"first-batch-{i}"}, 60, "loc", [])

    crystal_1 = await engine.auto_crystallize_if_needed("c1")
    assert crystal_1 is not None
    assert crystal_1.event_count == engine.AUTO_CRYSTALLIZE_THRESHOLD

    for i in range(engine.AUTO_CRYSTALLIZE_THRESHOLD - 1):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"second-batch-{i}"}, 60, "loc", [])

    crystal_mid = await engine.auto_crystallize_if_needed("c1")
    assert crystal_mid is None  # still below threshold for new events

    event_store.append("c1", EventType.PLAYER_ACTION, {"text": "second-batch-last"}, 60, "loc", [])
    crystal_2 = await engine.auto_crystallize_if_needed("c1")

    assert crystal_2 is not None
    assert crystal_2.event_count == engine.AUTO_CRYSTALLIZE_THRESHOLD
    assert crystal_2.content == "summary-2"


@pytest.mark.asyncio
async def test_context_window_uses_ai_crystal_and_only_uncrystallized_delta(event_store):
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps({"ai_memory": "AI_CHAIN_A", "player_summary": "Exec summary A"})
    )
    engine = MemoryEngine(event_store=event_store, llm=llm)

    for i in range(engine.AUTO_CRYSTALLIZE_THRESHOLD):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"old-event-{i}"}, 60, "loc", [])

    crystal = await engine.auto_crystallize_if_needed("c1")
    assert crystal is not None

    event_store.append("c1", EventType.PLAYER_ACTION, {"text": "new-delta-event"}, 60, "loc", [])
    context = engine.build_context_window("c1")

    assert "AI_CHAIN_A" in context
    assert "new-delta-event" in context
    assert "old-event-0" not in context
