import pytest
import json
from unittest.mock import AsyncMock
from app.engines.plot_generator import (
    AUTO_PLOT_RULES,
    AutoPlotRule,
    GeneratedNPC,
    PlotGenerator,
    RandomEvent,
)


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
async def test_generate_npc_allows_supporting_character_without_secret(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps({
        "name": "Mira Sol",
        "personality": "Practical and patient",
        "power_level": 2,
        "goal": "Finish today's deliveries",
        "appearance": "A courier in a blue coat",
    }))

    npc = await generator.generate_npc(world_context="A busy public market")

    assert npc.secret == ""
    prompt = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "Most supporting NPCs do not need a secret" in prompt


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

    prompt = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "direct, visible development" in prompt
    assert "Prefer open goals and conflicts" in prompt


@pytest.mark.asyncio
async def test_generate_npc_handles_malformed_json(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not json at all")
    npc = await generator.generate_npc(world_context="test")
    # Should return None (skip) rather than crash or return garbage
    assert npc is None


@pytest.mark.asyncio
async def test_generate_npc_returns_none_on_none_response(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="NONE")
    npc = await generator.generate_npc(world_context="test")
    assert npc is None


@pytest.mark.asyncio
async def test_generate_plot_arc_returns_none_on_none_response(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="None")
    arc = await generator.generate_plot_arc(world_context="test")
    assert arc is None


@pytest.mark.asyncio
async def test_generate_micro_hook_returns_none_on_none_response(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="none")
    hook = await generator.generate_micro_hook(world_context="test", recent_narrative="test")
    assert hook is None


@pytest.mark.asyncio
async def test_generate_micro_hook_does_not_default_to_hidden_plot(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="The class bell announces the next lesson.")

    hook = await generator.generate_micro_hook(
        world_context="A public academy",
        recent_narrative="Students wait in the courtyard.",
    )

    assert hook.description
    prompt = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "must not create a new mystery" in prompt
    assert "return NONE" in prompt


def test_default_auto_plot_rules_leave_room_between_injections():
    assert AUTO_PLOT_RULES["micro_hook"].cooldown_turns >= 6
    assert AUTO_PLOT_RULES["npc"].cooldown_turns >= 10
    assert AUTO_PLOT_RULES["plot_arc"].cooldown_turns >= 14


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
