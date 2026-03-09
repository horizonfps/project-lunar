import pytest
from app.db.scenario_store import ScenarioStore, Scenario, Campaign, StoryCard, StoryCardType


@pytest.fixture
def store(tmp_path):
    store = ScenarioStore(str(tmp_path / "test_scenarios.db"))
    yield store
    store.close()


def test_create_and_get_scenario(store):
    scenario = store.create_scenario(
        title="The Shattered Realm",
        description="A world broken by ancient magic",
        tone_instructions="Dark and gritty. High mortality.",
        opening_narrative="You wake in the ruins of a city...",
        language="en",
    )
    fetched = store.get_scenario(scenario.id)
    assert fetched is not None
    assert fetched.title == "The Shattered Realm"
    assert fetched.language == "en"


def test_add_story_card(store):
    scenario = store.create_scenario("Test", "", "", "", "en")
    card = store.add_story_card(
        scenario_id=scenario.id,
        card_type=StoryCardType.NPC,
        name="Mordain the Warlord",
        content={"personality": "brutal", "secret": "fears death", "power_level": 9},
    )
    assert card.id is not None
    assert card.name == "Mordain the Warlord"
    cards = store.get_story_cards(scenario.id)
    assert len(cards) == 1
    assert cards[0].card_type == StoryCardType.NPC


def test_create_campaign(store):
    scenario = store.create_scenario("Test", "", "", "", "en")
    campaign = store.create_campaign(scenario_id=scenario.id, player_name="Aria")
    assert campaign.id is not None
    assert campaign.scenario_id == scenario.id
    assert campaign.player_name == "Aria"


def test_list_scenarios(store):
    store.create_scenario("Scenario A", "", "", "", "en")
    store.create_scenario("Scenario B", "", "", "", "en")
    scenarios = store.list_scenarios()
    assert len(scenarios) == 2
    titles = [s.title for s in scenarios]
    assert "Scenario A" in titles
    assert "Scenario B" in titles


def test_get_campaigns_for_scenario(store):
    scenario = store.create_scenario("Test", "", "", "", "en")
    store.create_campaign(scenario.id, "Player1")
    store.create_campaign(scenario.id, "Player2")
    campaigns = store.get_campaigns(scenario.id)
    assert len(campaigns) == 2
