import pytest
from unittest.mock import AsyncMock
from app.engines.journal_engine import JournalEngine, JournalEntry, JournalCategory


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def engine(mock_llm):
    return JournalEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_logs_significant_decision(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value=(
        '{"relevant": true, "category": "DECISION", '
        '"summary": "Player refused the king\'s offer of gold."}'
    ))
    entry = await engine.evaluate_and_log(
        campaign_id="c1",
        narrative_text="The king offers you a bag of gold to betray your friends. You refuse.",
    )
    assert entry is not None
    assert entry.category == JournalCategory.DECISION
    assert "refused" in entry.summary.lower() or "king" in entry.summary.lower()


@pytest.mark.asyncio
async def test_skips_irrelevant_event(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value=(
        '{"relevant": false, "category": null, "summary": null}'
    ))
    entry = await engine.evaluate_and_log(
        campaign_id="c1",
        narrative_text="You walk down a dusty road. The sun is warm.",
    )
    assert entry is None


@pytest.mark.asyncio
async def test_logs_combat_event(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value=(
        '{"relevant": true, "category": "COMBAT", '
        '"summary": "Player defeated the warlord Mordain in single combat."}'
    ))
    entry = await engine.evaluate_and_log(
        campaign_id="c1",
        narrative_text="You strike the killing blow. Mordain falls.",
    )
    assert entry is not None
    assert entry.category == JournalCategory.COMBAT


def test_get_journal_returns_entries(engine):
    from datetime import datetime
    engine._journals["c1"] = [
        JournalEntry("c1", JournalCategory.DISCOVERY, "Found the hidden cave", datetime.utcnow().isoformat()),
        JournalEntry("c1", JournalCategory.COMBAT, "Fought the dragon", datetime.utcnow().isoformat()),
    ]
    entries = engine.get_journal("c1")
    assert len(entries) == 2


def test_get_by_category_filters(engine):
    from datetime import datetime
    engine._journals["c1"] = [
        JournalEntry("c1", JournalCategory.DISCOVERY, "Found cave", datetime.utcnow().isoformat()),
        JournalEntry("c1", JournalCategory.COMBAT, "Fought dragon", datetime.utcnow().isoformat()),
        JournalEntry("c1", JournalCategory.DISCOVERY, "Found map", datetime.utcnow().isoformat()),
    ]
    discoveries = engine.get_by_category("c1", JournalCategory.DISCOVERY)
    assert len(discoveries) == 2
    assert all(e.category == JournalCategory.DISCOVERY for e in discoveries)


@pytest.mark.asyncio
async def test_handles_malformed_json(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not json")
    entry = await engine.evaluate_and_log("c1", "Something happened.")
    assert entry is None  # graceful fallback


@pytest.mark.asyncio
async def test_handles_fenced_json(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='```json\n{"relevant": true, "category": "WORLD_EVENT", "summary": "War spreads across the border."}\n```'
    )
    entry = await engine.evaluate_and_log("c1", "A war begins in the north.")
    assert entry is not None
    assert entry.category == JournalCategory.WORLD_EVENT


@pytest.mark.asyncio
async def test_fallback_heuristic_when_json_missing(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not json")
    entry = await engine.evaluate_and_log("c1", "You attack the warlord and parry his strike.")
    assert entry is not None
    assert entry.category == JournalCategory.COMBAT


@pytest.mark.asyncio
async def test_inferred_category_can_override_discovery(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"relevant": true, "category": "DISCOVERY", "summary": "Something was revealed."}'
    )
    entry = await engine.evaluate_and_log("c1", "Time passes and factions in the capital shift alliances.")
    assert entry is not None
    assert entry.category == JournalCategory.WORLD_EVENT


def test_log_player_action_decision(engine):
    entry = engine.log_player_action("c1", "I decide to accept the guard's terms.")
    assert entry is not None
    assert entry.category == JournalCategory.DECISION


def test_log_player_action_relationship(engine):
    entry = engine.log_player_action("c1", "I ask the guard for safe passage.")
    assert entry is not None
    assert entry.category == JournalCategory.RELATIONSHIP_CHANGE
