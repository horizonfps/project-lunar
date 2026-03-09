import pytest
import tempfile
import os
from app.db.event_store import EventStore, Event, EventType


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_events.db")
    store = EventStore(db_path)
    yield store
    store.close()


def test_append_event(store):
    event = store.append(
        campaign_id="campaign-1",
        event_type=EventType.PLAYER_ACTION,
        payload={"text": "I open the door"},
        narrative_time_delta=60,
        location="tavern",
        entities=["player", "door"],
    )
    assert event.id is not None
    assert event.event_type == EventType.PLAYER_ACTION


def test_get_recent_events(store):
    for i in range(5):
        store.append(
            campaign_id="campaign-1",
            event_type=EventType.PLAYER_ACTION,
            payload={"text": f"action {i}"},
            narrative_time_delta=60,
            location="tavern",
            entities=["player"],
        )
    events = store.get_recent(campaign_id="campaign-1", limit=3)
    assert len(events) == 3


def test_get_total_narrative_time(store):
    store.append("c1", EventType.PLAYER_ACTION, {}, 3600, "loc", [])
    store.append("c1", EventType.WORLD_TICK, {}, 86400, "loc", [])
    total = store.get_total_narrative_time("c1")
    assert total == 3600 + 86400


def test_events_are_immutable(store):
    event = store.append("c1", EventType.PLAYER_ACTION, {"text": "hi"}, 0, "loc", [])
    with pytest.raises(Exception):
        object.__setattr__(event, "payload", {"text": "modified"})
