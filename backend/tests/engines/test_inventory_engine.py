import os
import pytest
from app.db.event_store import EventStore
from app.engines.inventory_engine import InventoryEngine


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_events.db")
    es = EventStore(db_path)
    yield es
    es.close()


@pytest.fixture
def engine(store):
    return InventoryEngine(event_store=store)


CAMPAIGN = "test-campaign-001"


def test_empty_inventory(engine):
    items = engine.get_inventory(CAMPAIGN)
    assert items == []


def test_add_item(engine):
    engine.add_item(CAMPAIGN, "Iron Sword", "weapon", "blacksmith")
    items = engine.get_inventory(CAMPAIGN)
    assert len(items) == 1
    assert items[0].name == "Iron Sword"
    assert items[0].category == "weapon"
    assert items[0].source == "blacksmith"
    assert items[0].status == "carried"


def test_use_item(engine):
    engine.add_item(CAMPAIGN, "Health Potion", "consumable", "merchant")
    engine.use_item(CAMPAIGN, "Health Potion")
    items = engine.get_inventory(CAMPAIGN)
    assert len(items) == 1
    assert items[0].status == "used"


def test_lose_item(engine):
    engine.add_item(CAMPAIGN, "Gold Ring", "accessory", "treasure chest")
    engine.lose_item(CAMPAIGN, "Gold Ring")
    items = engine.get_inventory(CAMPAIGN)
    assert len(items) == 1
    assert items[0].status == "lost"


def test_get_carried_items(engine):
    engine.add_item(CAMPAIGN, "Iron Sword", "weapon", "blacksmith")
    engine.add_item(CAMPAIGN, "Health Potion", "consumable", "merchant")
    engine.use_item(CAMPAIGN, "Health Potion")
    carried = engine.get_carried_items(CAMPAIGN)
    assert len(carried) == 1
    assert carried[0].name == "Iron Sword"


def test_use_nonexistent_item_is_noop(engine):
    engine.use_item(CAMPAIGN, "Phantom Blade")
    items = engine.get_inventory(CAMPAIGN)
    assert items == []


def test_format_for_prompt(engine):
    assert engine.format_for_prompt(CAMPAIGN) == "INVENTORY: Empty."
    engine.add_item(CAMPAIGN, "Iron Sword", "weapon", "blacksmith")
    engine.add_item(CAMPAIGN, "Health Potion", "consumable", "merchant")
    engine.use_item(CAMPAIGN, "Health Potion")
    prompt = engine.format_for_prompt(CAMPAIGN)
    assert "INVENTORY:" in prompt
    assert "Iron Sword [weapon]" in prompt
    assert "status: carried" in prompt
    assert "Health Potion [consumable]" in prompt
    assert "status: used" in prompt


def test_duplicate_add_ignored(engine):
    engine.add_item(CAMPAIGN, "Iron Sword", "weapon", "blacksmith")
    engine.add_item(CAMPAIGN, "iron sword", "weapon", "another source")
    items = engine.get_inventory(CAMPAIGN)
    assert len(items) == 1
    assert items[0].source == "blacksmith"  # original kept
