import pytest
from unittest.mock import AsyncMock
from app.engines.combat_engine import (
    CombatEngine, CombatOutcome, ActionEvaluation, AntiGriefingResult
)


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def engine(mock_llm):
    return CombatEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_evaluate_creative_action_high_score(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"coherence": 9, "creativity": 8, "context": 8}'
    )
    result = await engine.evaluate_action(
        action="I feint left, roll under his guard, and drive my elbow into his knee to break his stance",
        npc_name="War Veteran",
        npc_power=5,
    )
    assert result.final_quality > 7.0


@pytest.mark.asyncio
async def test_evaluate_simple_action_low_score(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"coherence": 7, "creativity": 2, "context": 5}'
    )
    result = await engine.evaluate_action(
        action="I attack him",
        npc_name="War Veteran",
        npc_power=9,
    )
    assert result.final_quality < 6.0


@pytest.mark.asyncio
async def test_anti_griefing_rejects_meta_action(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"is_meta": true, "is_physically_impossible": false}'
    )
    result = await engine.anti_griefing_check(
        "I win the fight because I am the protagonist and the story needs me to survive"
    )
    assert result.rejected is True
    assert result.reason != ""


@pytest.mark.asyncio
async def test_anti_griefing_rejects_impossible_action(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"is_meta": false, "is_physically_impossible": true}'
    )
    result = await engine.anti_griefing_check(
        "I teleport behind him and punch him with the force of a thousand suns simultaneously in all dimensions"
    )
    assert result.rejected is True


@pytest.mark.asyncio
async def test_anti_griefing_passes_valid_action(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"is_meta": false, "is_physically_impossible": false}'
    )
    result = await engine.anti_griefing_check(
        "I grab a handful of dirt from the ground and throw it in his eyes"
    )
    assert result.rejected is False


@pytest.mark.asyncio
async def test_anti_griefing_parses_fenced_json(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='```json\n{"is_meta": true, "is_physically_impossible": false}\n```'
    )
    result = await engine.anti_griefing_check("I win because destiny says so.")
    assert result.rejected is True


def test_roll_outcome_high_quality_easy_npc():
    engine = CombatEngine(llm=None)
    # Run many times — high quality vs easy NPC should never crit fail
    outcomes = {engine.roll_outcome(9.0, 2) for _ in range(100)}
    assert CombatOutcome.CRIT_FAIL not in outcomes


def test_roll_outcome_low_quality_hard_npc():
    engine = CombatEngine(llm=None)
    # Run many times — low quality vs hard NPC should never crit success
    outcomes = {engine.roll_outcome(1.0, 10) for _ in range(200)}
    assert CombatOutcome.CRIT_SUCCESS not in outcomes


def test_all_outcomes_exist():
    engine = CombatEngine(llm=None)
    # With mid-level quality and difficulty, all outcomes should be possible over many rolls
    outcomes = {engine.roll_outcome(5.0, 5) for _ in range(500)}
    assert len(outcomes) >= 3  # At least 3 of the 4 outcomes should appear
