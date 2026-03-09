import pytest
import json
from unittest.mock import AsyncMock
from app.services.scenario_service import ScenarioService
from app.db.scenario_store import ScenarioStore, StoryCardType


@pytest.fixture
def store(tmp_path):
    s = ScenarioStore(str(tmp_path / "scenarios.db"))
    yield s
    s.close()


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def service(store, mock_llm):
    return ScenarioService(store=store, llm=mock_llm)


@pytest.mark.asyncio
async def test_extract_lore_creates_npc_cards(service, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps([
        {"type": "NPC", "name": "King Aldric", "content": {"personality": "noble", "power_level": 8, "secret": "fears Seraphine"}},
        {"type": "NPC", "name": "Seraphine", "content": {"personality": "mysterious", "power_level": 9, "secret": "unknown origin"}},
        {"type": "LOCATION", "name": "Iron Citadel", "content": {"description": "Fortress of the king"}},
    ]))
    scenario = service.store.create_scenario("Test", "", "", "", "en")
    cards = await service.extract_lore_to_cards(
        scenario_id=scenario.id,
        lore_text="King Aldric rules from the Iron Citadel. He fears the witch Seraphine.",
    )
    assert len(cards) == 3
    names = [c.name for c in cards]
    assert "King Aldric" in names
    assert "Seraphine" in names
    assert "Iron Citadel" in names


@pytest.mark.asyncio
async def test_extract_lore_skips_invalid_types(service, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json.dumps([
        {"type": "INVALID_TYPE", "name": "Bad Entity", "content": {}},
        {"type": "NPC", "name": "Valid NPC", "content": {"power_level": 5}},
    ]))
    scenario = service.store.create_scenario("Test", "", "", "", "en")
    cards = await service.extract_lore_to_cards(scenario.id, "Some lore text")
    assert len(cards) == 1
    assert cards[0].name == "Valid NPC"


@pytest.mark.asyncio
async def test_extract_lore_handles_malformed_json(service, mock_llm):
    mock_llm.complete = AsyncMock(return_value="not json at all")
    scenario = service.store.create_scenario("Test", "", "", "", "en")
    cards = await service.extract_lore_to_cards(scenario.id, "Some lore text")
    assert cards == []


@pytest.mark.asyncio
async def test_extract_lore_empty_text_returns_empty(service, mock_llm):
    mock_llm.complete = AsyncMock(return_value="[]")
    scenario = service.store.create_scenario("Test", "", "", "", "en")
    cards = await service.extract_lore_to_cards(scenario.id, "")
    assert cards == []


def test_service_exposes_store(service):
    assert service.store is not None
    scenario = service.store.create_scenario("Direct", "", "", "", "en")
    assert scenario.title == "Direct"
