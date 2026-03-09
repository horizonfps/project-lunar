import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engines.narrator_engine import NarratorEngine, NarrativeMode


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def engine(mock_llm):
    return NarratorEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_detect_combat_mode(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"mode": "COMBAT", "ambush": false, "narrative_time_seconds": 0}'
    )
    mode, meta = await engine.detect_mode("I draw my sword and charge at the bandit!")
    assert mode == NarrativeMode.COMBAT
    assert meta["ambush"] is False
    assert meta["narrative_time_seconds"] == 0


@pytest.mark.asyncio
async def test_detect_narrative_mode(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"mode": "NARRATIVE", "ambush": false, "narrative_time_seconds": 3600}'
    )
    mode, meta = await engine.detect_mode("I walk to the market and ask about rumors")
    assert mode == NarrativeMode.NARRATIVE
    assert meta["narrative_time_seconds"] == 3600


@pytest.mark.asyncio
async def test_detect_meta_mode(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"mode": "META", "ambush": false, "narrative_time_seconds": 0}'
    )
    mode, meta = await engine.detect_mode("Can you make the story more dramatic?")
    assert mode == NarrativeMode.META


@pytest.mark.asyncio
async def test_detect_mode_defaults_on_bad_json(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not valid json at all")
    mode, meta = await engine.detect_mode("I do something")
    assert mode == NarrativeMode.NARRATIVE  # safe default
    assert meta["narrative_time_seconds"] == 60


@pytest.mark.asyncio
async def test_detect_mode_parses_fenced_json(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='```json\n{"mode": "COMBAT", "ambush": false, "narrative_time_seconds": 12}\n```'
    )
    mode, meta = await engine.detect_mode("I slash at the guard")
    assert mode == NarrativeMode.COMBAT
    assert meta["mode"] == "COMBAT"
    assert meta["narrative_time_seconds"] == 12


@pytest.mark.asyncio
async def test_detect_ambush(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"mode": "COMBAT", "ambush": true, "narrative_time_seconds": 0}'
    )
    mode, meta = await engine.detect_mode("Suddenly an assassin leaps from the shadows!")
    assert mode == NarrativeMode.COMBAT
    assert meta["ambush"] is True


def test_build_system_prompt_includes_tone(engine):
    prompt = engine.build_system_prompt(
        tone_instructions="Dark and hopeless. No happy endings.",
        memory_context="",
        language="en",
    )
    assert "Dark and hopeless" in prompt


def test_build_system_prompt_includes_memory(engine):
    prompt = engine.build_system_prompt(
        tone_instructions="",
        memory_context="The player betrayed the king in the last session.",
        language="en",
    )
    assert "betrayed the king" in prompt


def test_build_system_prompt_includes_inventory_context(engine):
    prompt = engine.build_system_prompt(
        tone_instructions="",
        memory_context="",
        language="en",
        inventory_context="INVENTORY:\n- Soul-Lock Pistol [weapon] (source: Blacktide's cabin) — status: carried",
    )
    assert "Soul-Lock Pistol" in prompt
    assert "ITEM_ADD" in prompt


def test_build_system_prompt_without_inventory_still_works(engine):
    """Existing callers that don't pass inventory_context should still work."""
    prompt = engine.build_system_prompt(
        tone_instructions="Dark",
        memory_context="",
        language="en",
    )
    assert "Dark" in prompt
    assert "ITEM_ADD" in prompt  # rules always present


def test_build_system_prompt_language_portuguese(engine):
    prompt = engine.build_system_prompt(
        tone_instructions="",
        memory_context="",
        language="pt-br",
    )
    assert "pt-br" in prompt or "português" in prompt.lower() or "portuguese" in prompt.lower()


def test_build_meta_prompt_is_out_of_character(engine):
    prompt = engine.build_meta_prompt(
        language="en",
        inventory_context="INVENTORY:\n- Sword [weapon] — carried",
        journal_context="Found a hidden passage (action 5)",
        npc_context="Captain Blacktide: feeling angry",
    )
    assert "Game Master" in prompt
    assert "OUT-OF-CHARACTER" in prompt
    assert "Sword" in prompt
    assert "Blacktide" in prompt
    assert "hidden passage" in prompt
    assert "Never break character" not in prompt
    assert "immersive" not in prompt.lower()


def test_build_meta_prompt_language_pt_br(engine):
    prompt = engine.build_meta_prompt(
        language="pt-br",
        inventory_context="",
        journal_context="",
        npc_context="",
    )
    assert "pt-br" in prompt or "português" in prompt.lower()


def test_build_meta_prompt_empty_contexts(engine):
    prompt = engine.build_meta_prompt(language="en")
    assert "Game Master" in prompt
    assert "INVENTORY" not in prompt
    assert "JOURNAL" not in prompt
    assert "ACTIVE NPCs" not in prompt
