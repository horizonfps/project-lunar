import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engines.journal_engine import JournalEntry, JournalCategory
from app.engines.narrator_engine import NarrativeMode
from app.engines.plot_generator import AutoPlotRule, GeneratedNPC
from app.db.event_store import EventType


async def async_gen(*items):
    for item in items:
        yield item


@pytest.fixture
def mock_narrator():
    m = MagicMock()
    m.detect_mode = AsyncMock(return_value=(
        "NARRATIVE",
        {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 60}
    ))
    m.build_system_prompt = MagicMock(return_value="You are a narrator.")
    m.stream_narrative = MagicMock(return_value=async_gen("Once", " upon", " a time"))
    return m


@pytest.fixture
def mock_memory():
    m = MagicMock()
    m.build_context_window = MagicMock(return_value="Previous events...")
    m.build_context_window_async = AsyncMock(return_value="Previous events...")
    return m


@pytest.fixture
def mock_world_reactor():
    m = MagicMock()
    m.process_tick = AsyncMock(return_value="")
    return m


@pytest.fixture
def mock_journal():
    m = MagicMock()
    m.evaluate_and_log = AsyncMock(return_value=None)
    return m


@pytest.fixture
def mock_event_store():
    m = MagicMock()
    m.append = MagicMock()
    return m


@pytest.fixture
def mock_combat():
    m = MagicMock()
    m.anti_griefing_check = AsyncMock(return_value=MagicMock(rejected=False))
    m.evaluate_action = AsyncMock(return_value=MagicMock(final_quality=8.0))
    m.roll_outcome = MagicMock(return_value="SUCCESS")
    return m


@pytest.fixture
def session(mock_narrator, mock_memory, mock_world_reactor, mock_journal, mock_event_store, mock_combat):
    from app.services.game_session import GameSession
    return GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark and gritty.",
        language="en",
        narrator=mock_narrator,
        memory=mock_memory,
        world_reactor=mock_world_reactor,
        journal=mock_journal,
        event_store=mock_event_store,
        combat_engine=mock_combat,
    )


@pytest.mark.asyncio
async def test_narrative_action_streams_chunks(session):
    chunks = []
    async for chunk in session.process_action("I walk to the tavern"):
        chunks.append(chunk)
    assert len(chunks) > 0
    assert "Once" in chunks or any("Once" in c for c in chunks)


@pytest.mark.asyncio
async def test_narrative_action_logs_to_event_store(session, mock_event_store):
    async for _ in session.process_action("I look around"):
        pass
    assert mock_event_store.append.called


@pytest.mark.asyncio
async def test_narrative_action_triggers_world_tick(session, mock_world_reactor):
    async for _ in session.process_action("I travel for a month"):
        pass
    assert mock_world_reactor.process_tick.called


@pytest.mark.asyncio
async def test_combat_action_goes_through_combat_engine(session, mock_narrator, mock_combat):
    mock_narrator.detect_mode = AsyncMock(return_value=(
        "COMBAT",
        {"mode": "COMBAT", "ambush": False, "narrative_time_seconds": 0}
    ))
    chunks = []
    async for chunk in session.process_action("I attack the bandit"):
        chunks.append(chunk)
    assert mock_combat.anti_griefing_check.called
    assert mock_combat.evaluate_action.called


@pytest.mark.asyncio
async def test_combat_action_with_enum_mode_goes_through_combat_engine(session, mock_narrator, mock_combat):
    mock_narrator.detect_mode = AsyncMock(return_value=(
        NarrativeMode.COMBAT,
        {"mode": "COMBAT", "ambush": False, "narrative_time_seconds": 0}
    ))
    async for _ in session.process_action("I attack the bandit"):
        pass
    assert mock_combat.anti_griefing_check.called
    assert mock_combat.evaluate_action.called


@pytest.mark.asyncio
async def test_combat_griefing_stops_processing(session, mock_narrator, mock_combat):
    mock_narrator.detect_mode = AsyncMock(return_value=(
        "COMBAT",
        {"mode": "COMBAT", "ambush": False, "narrative_time_seconds": 0}
    ))
    mock_combat.anti_griefing_check = AsyncMock(
        return_value=MagicMock(rejected=True, reason="Meta-gaming detected.")
    )
    chunks = []
    async for chunk in session.process_action("I win because I am the hero"):
        chunks.append(chunk)
    combined = "".join(chunks)
    assert "Meta-gaming" in combined or "narrator" in combined.lower()
    # Combat evaluate should NOT be called
    assert not mock_combat.evaluate_action.called


@pytest.mark.asyncio
async def test_journal_entry_emitted_as_sse():
    """Journal entries should be yielded as JSON-prefixed chunks."""
    narrator = MagicMock()
    narrator.detect_mode = AsyncMock(return_value=(
        "NARRATIVE",
        {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 60}
    ))
    narrator.build_system_prompt = MagicMock(return_value="You are a narrator.")
    narrator.stream_narrative = MagicMock(return_value=async_gen("A hidden passage opens."))

    journal_entry = JournalEntry(
        campaign_id="test-campaign",
        category=JournalCategory.DISCOVERY,
        summary="Found a hidden passage.",
        created_at="2026-03-10T00:00:00",
    )
    journal = MagicMock()
    journal.evaluate_and_log = AsyncMock(return_value=journal_entry)

    memory = MagicMock()
    memory.build_context_window = MagicMock(return_value="Previous events...")

    world_reactor = MagicMock()
    world_reactor.process_tick = AsyncMock(return_value="")

    event_store = MagicMock()
    event_store.append = MagicMock()

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark and gritty.",
        language="en",
        narrator=narrator,
        memory=memory,
        world_reactor=world_reactor,
        journal=journal,
        event_store=event_store,
    )

    chunks = []
    async for chunk in session.process_action("I search the wall"):
        chunks.append(chunk)

    journal_chunks = [c for c in chunks if c.startswith("[JOURNAL]")]
    assert len(journal_chunks) == 1

    payload = json.loads(journal_chunks[0][len("[JOURNAL]"):])
    assert payload["category"] == "DISCOVERY"
    assert payload["summary"] == "Found a hidden passage."


@pytest.mark.asyncio
async def test_process_action_ingests_to_graphiti(
    mock_narrator, mock_memory, mock_world_reactor, mock_journal, mock_event_store, mock_combat
):
    """Narrator responses should be ingested into the Graphiti temporal knowledge graph."""
    mock_graphiti = MagicMock()
    mock_graphiti.ingest_episode = AsyncMock()

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark and gritty.",
        language="en",
        narrator=mock_narrator,
        memory=mock_memory,
        world_reactor=mock_world_reactor,
        journal=mock_journal,
        event_store=mock_event_store,
        combat_engine=mock_combat,
        graphiti_engine=mock_graphiti,
    )

    async for _ in session.process_action("I open the ancient door"):
        pass

    mock_graphiti.ingest_episode.assert_called()
    # Verify it was called with the right campaign and description
    call_kwargs = mock_graphiti.ingest_episode.call_args
    assert call_kwargs.kwargs["campaign_id"] == "test-campaign"
    assert call_kwargs.kwargs["description"] == "narrator_response"


@pytest.mark.asyncio
async def test_process_action_triggers_auto_plot_generation_npc():
    narrator = MagicMock()
    narrator.detect_mode = AsyncMock(return_value=(
        "NARRATIVE",
        {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 600},
    ))
    narrator.build_system_prompt = MagicMock(return_value="You are a narrator.")
    narrator.stream_narrative = MagicMock(return_value=async_gen("A corridor opens."))

    memory = MagicMock()
    memory.build_context_window = MagicMock(return_value="MEM_CTX")

    world_reactor = MagicMock()
    world_reactor.process_tick = AsyncMock(return_value="")

    journal = MagicMock()
    journal.evaluate_and_log = AsyncMock(return_value=None)

    event_store = MagicMock()
    event_store.append = MagicMock()
    event_store.get_total_narrative_time = MagicMock(return_value=7200)

    plot_generator = MagicMock()
    plot_generator.should_trigger_auto = MagicMock(return_value=True)
    plot_generator.generate_npc = AsyncMock(
        return_value=GeneratedNPC(
            name="Captain Riven",
            personality="Cold strategist",
            power_level=7,
            secret="Works for two factions",
            goal="Capture the player alive",
            appearance="Scarred veteran in black armor",
        )
    )

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark and gritty.",
        language="en",
        narrator=narrator,
        memory=memory,
        world_reactor=world_reactor,
        journal=journal,
        event_store=event_store,
        plot_generator=plot_generator,
        auto_plot_rules={
            "npc": AutoPlotRule(
                kind="npc",
                min_turns=1,
                min_narrative_seconds=0,
                cooldown_turns=99,
                cooldown_narrative_seconds=999999,
            )
        },
    )

    chunks = []
    async for chunk in session.process_action("I inspect the hallway"):
        chunks.append(chunk)

    auto_chunks = [chunk for chunk in chunks if chunk.startswith("[PLOT_AUTO]")]
    assert len(auto_chunks) == 1
    payload = json.loads(auto_chunks[0][len("[PLOT_AUTO]"):])
    assert payload["kind"] == "npc"
    assert payload["data"]["name"] == "Captain Riven"
    assert any(call.kwargs.get("event_type") == EventType.PLOT_GENERATION for call in event_store.append.call_args_list)


@pytest.mark.asyncio
async def test_auto_plot_respects_cooldown_between_actions():
    narrator = MagicMock()
    narrator.detect_mode = AsyncMock(return_value=(
        "NARRATIVE",
        {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 600},
    ))
    narrator.build_system_prompt = MagicMock(return_value="You are a narrator.")
    narrator.stream_narrative = MagicMock(return_value=async_gen("Narrative chunk."))

    memory = MagicMock()
    memory.build_context_window = MagicMock(return_value="MEM_CTX")

    world_reactor = MagicMock()
    world_reactor.process_tick = AsyncMock(return_value="")

    journal = MagicMock()
    journal.evaluate_and_log = AsyncMock(return_value=None)

    event_store = MagicMock()
    event_store.append = MagicMock()
    event_store.get_total_narrative_time = MagicMock(side_effect=[3600, 3600])

    plot_generator = MagicMock()
    plot_generator.should_trigger_auto = MagicMock(side_effect=[True, False])
    plot_generator.generate_npc = AsyncMock(
        return_value=GeneratedNPC(
            name="Lyra",
            personality="Pragmatic",
            power_level=5,
            secret="Ex-spy",
            goal="Survive the siege",
            appearance="Leather cloak and silver dagger",
        )
    )

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark and gritty.",
        language="en",
        narrator=narrator,
        memory=memory,
        world_reactor=world_reactor,
        journal=journal,
        event_store=event_store,
        plot_generator=plot_generator,
        auto_plot_rules={
            "npc": AutoPlotRule(
                kind="npc",
                min_turns=1,
                min_narrative_seconds=0,
                cooldown_turns=5,
                cooldown_narrative_seconds=2000,
            )
        },
    )

    async for _ in session.process_action("first action"):
        pass
    async for _ in session.process_action("second action"):
        pass

    assert plot_generator.generate_npc.await_count == 1


@pytest.mark.asyncio
async def test_inventory_tags_parsed_from_narrative():
    """[ITEM_ADD] tags in narrative should create inventory events."""
    narrator = MagicMock()
    narrator.detect_mode = AsyncMock(return_value=(
        "NARRATIVE",
        {"mode": "NARRATIVE", "ambush": False, "narrative_time_seconds": 60}
    ))
    narrator.build_system_prompt = MagicMock(return_value="You are a narrator.")
    narrator.stream_narrative = MagicMock(return_value=async_gen(
        "You find a gleaming sword. [ITEM_ADD:Gleaming Sword|weapon|Found on ground] It shines."
    ))

    journal = MagicMock()
    journal.evaluate_and_log = AsyncMock(return_value=None)

    memory = MagicMock()
    memory.build_context_window = MagicMock(return_value="ctx")
    memory.auto_crystallize_if_needed = AsyncMock(return_value=None)

    world_reactor = MagicMock()
    world_reactor.process_tick = AsyncMock(return_value="")

    event_store = MagicMock()
    event_store.append = MagicMock()
    event_store.get_by_type = MagicMock(return_value=[])

    from app.engines.inventory_engine import InventoryEngine
    inventory = InventoryEngine(event_store=event_store)

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="",
        language="en",
        narrator=narrator,
        memory=memory,
        world_reactor=world_reactor,
        journal=journal,
        event_store=event_store,
        inventory_engine=inventory,
    )

    chunks = []
    async for chunk in session.process_action("I search the room"):
        chunks.append(chunk)

    inv_chunks = [c for c in chunks if c.startswith("[INVENTORY]")]
    assert len(inv_chunks) == 1
    payload = json.loads(inv_chunks[0][len("[INVENTORY]"):])
    assert payload["action"] == "add"
    assert payload["name"] == "Gleaming Sword"


@pytest.mark.asyncio
async def test_meta_mode_uses_meta_prompt():
    """META mode should use build_meta_prompt, not build_system_prompt."""
    narrator = MagicMock()
    narrator.detect_mode = AsyncMock(return_value=(
        NarrativeMode.META,
        {"mode": "META", "ambush": False, "narrative_time_seconds": 0}
    ))
    narrator.build_meta_prompt = MagicMock(return_value="You are a Game Master.")
    narrator.build_system_prompt = MagicMock(return_value="You are a narrator.")
    narrator.stream_narrative = MagicMock(return_value=async_gen("You have: Sword (carried)."))

    journal = MagicMock()
    journal.evaluate_and_log = AsyncMock(return_value=None)
    journal.get_journal = MagicMock(return_value=[])

    memory = MagicMock()
    memory.build_context_window = MagicMock(return_value="ctx")
    memory.auto_crystallize_if_needed = AsyncMock(return_value=None)

    world_reactor = MagicMock()
    world_reactor.process_tick = AsyncMock(return_value="")

    event_store = MagicMock()
    event_store.append = MagicMock()
    event_store.get_by_type = MagicMock(return_value=[])

    npc_minds = MagicMock()
    npc_minds.get_all_minds = MagicMock(return_value=[])

    from app.engines.inventory_engine import InventoryEngine
    inventory = InventoryEngine(event_store=event_store)

    from app.services.game_session import GameSession
    session = GameSession(
        campaign_id="test-campaign",
        scenario_tone="Dark",
        language="en",
        narrator=narrator,
        memory=memory,
        world_reactor=world_reactor,
        journal=journal,
        event_store=event_store,
        npc_minds=npc_minds,
        inventory_engine=inventory,
    )

    async for _ in session.process_action("[META] What items do I have?"):
        pass

    narrator.build_meta_prompt.assert_called_once()
    narrator.build_system_prompt.assert_not_called()
