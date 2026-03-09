import pytest
import json
from unittest.mock import AsyncMock
from app.engines.plot_generator import PlotGenerator, GeneratedNPC, RandomEvent, AutoPlotRule


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def generator(mock_llm):
    return PlotGenerator(llm=mock_llm)


@pytest.mark.asyncio
async def test_generate_npc_returns_valid_npc(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps({
        "name": "Seraphine the Pale",
        "personality": "Calculating and cold",
        "power_level": 7,
        "secret": "She is the king's illegitimate daughter",
        "goal": "Claim the throne without bloodshed",
        "appearance": "Tall, white hair, silver eyes",
    }))
    npc = await generator.generate_npc(world_context="A medieval kingdom in turmoil")
    assert npc.name == "Seraphine the Pale"
    assert npc.power_level == 7
    assert npc.secret is not None
    assert 1 <= npc.power_level <= 10


@pytest.mark.asyncio
async def test_generate_npc_clamps_power_level(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps({
        "name": "Test NPC",
        "personality": "Boring",
        "power_level": 15,  # out of range
        "secret": "none",
        "goal": "exist",
        "appearance": "generic",
    }))
    npc = await generator.generate_npc(world_context="test")
    assert npc.power_level == 10  # clamped


@pytest.mark.asyncio
async def test_generate_random_event(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps({
        "title": "The Wandering Merchant",
        "description": "A merchant arrives with goods from the north and unsettling rumors.",
        "choices": ["Buy from him", "Interrogate him", "Ignore him"],
    }))
    event = await generator.generate_random_event(
        location="Crossroads",
        world_context="War is approaching",
        narrative_time=86400,
    )
    assert event.title == "The Wandering Merchant"
    assert len(event.choices) == 3


@pytest.mark.asyncio
async def test_generate_plot_arc_returns_string(generator, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value="A merchant's stolen ledger holds the names of every spy in the city."
    )
    arc = await generator.generate_plot_arc(world_context="Trade city under occupation")
    assert isinstance(arc, str)
    assert len(arc) > 10


@pytest.mark.asyncio
async def test_generate_npc_handles_malformed_json(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not json at all")
    npc = await generator.generate_npc(world_context="test")
    # Should return a fallback NPC rather than crash
    assert npc is not None
    assert npc.name is not None


def test_should_trigger_auto_on_first_threshold(generator):
    rule = AutoPlotRule(
        kind="event",
        min_turns=3,
        min_narrative_seconds=600,
        cooldown_turns=4,
        cooldown_narrative_seconds=900,
    )
    assert generator.should_trigger_auto(rule, turns_since_last=3, narrative_seconds_since_last=600, trigger_count=0) is True
    assert generator.should_trigger_auto(rule, turns_since_last=2, narrative_seconds_since_last=9999, trigger_count=0) is False


def test_should_trigger_auto_uses_cooldown_after_first_trigger(generator):
    rule = AutoPlotRule(
        kind="npc",
        min_turns=2,
        min_narrative_seconds=60,
        cooldown_turns=5,
        cooldown_narrative_seconds=1800,
    )
    assert generator.should_trigger_auto(rule, turns_since_last=4, narrative_seconds_since_last=2000, trigger_count=1) is False
    assert generator.should_trigger_auto(rule, turns_since_last=5, narrative_seconds_since_last=1800, trigger_count=1) is True
