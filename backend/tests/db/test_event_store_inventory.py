"""Tests for the INVENTORY event type in EventStore."""

from app.db.event_store import EventStore, EventType


def test_inventory_event_type_exists():
    assert EventType.INVENTORY == "INVENTORY"
    assert EventType.INVENTORY.value == "INVENTORY"


def test_append_inventory_event(tmp_path):
    store = EventStore(str(tmp_path / "test.db"))
    event = store.append(
        campaign_id="camp-1",
        event_type=EventType.INVENTORY,
        payload={"action": "add", "item": "Iron Sword", "quantity": 1},
        narrative_time_delta=0,
        location="Blacksmith Shop",
        entities=["player", "iron_sword"],
    )

    assert event.event_type == EventType.INVENTORY
    assert event.campaign_id == "camp-1"
    assert event.payload["item"] == "Iron Sword"
    assert event.location == "Blacksmith Shop"
    assert event.entities == ["player", "iron_sword"]

    # Verify round-trip from DB
    events = store.get_recent("camp-1", limit=10)
    assert len(events) == 1
    retrieved = events[0]
    assert retrieved.id == event.id
    assert retrieved.event_type == EventType.INVENTORY
    assert retrieved.payload == {"action": "add", "item": "Iron Sword", "quantity": 1}
    assert retrieved.entities == ["player", "iron_sword"]

    store.close()


def test_get_inventory_events_by_type(tmp_path):
    store = EventStore(str(tmp_path / "test.db"))

    store.append(
        campaign_id="camp-1",
        event_type=EventType.INVENTORY,
        payload={"action": "add", "item": "Health Potion"},
        narrative_time_delta=0,
        location="Market",
        entities=["player"],
    )
    store.append(
        campaign_id="camp-1",
        event_type=EventType.NARRATOR_RESPONSE,
        payload={"text": "The merchant smiles."},
        narrative_time_delta=5,
        location="Market",
        entities=["merchant"],
    )
    store.append(
        campaign_id="camp-1",
        event_type=EventType.INVENTORY,
        payload={"action": "add", "item": "Rope"},
        narrative_time_delta=0,
        location="Market",
        entities=["player"],
    )

    inventory_events = store.get_by_type("camp-1", EventType.INVENTORY)
    assert len(inventory_events) == 2
    assert all(e.event_type == EventType.INVENTORY for e in inventory_events)

    store.close()
