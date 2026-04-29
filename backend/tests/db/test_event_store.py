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


# ── Camada 3 — witnessed_by perspective filter ─────────────────────


def test_append_defaults_witnessed_by_to_empty_list(store):
    event = store.append("c1", EventType.PLAYER_ACTION, {"text": "hi"}, 0, "loc", [])
    assert event.witnessed_by == []


def test_append_persists_witnessed_by(store):
    event = store.append(
        "c1", EventType.NARRATOR_RESPONSE, {"text": "scene"}, 0, "loc", [],
        witnessed_by=["Rin", "Kai"],
    )
    assert event.witnessed_by == ["Rin", "Kai"]
    # Round-trip through the store
    fetched = store.get_recent("c1", limit=1)[0]
    assert fetched.witnessed_by == ["Rin", "Kai"]


def test_update_witnessed_by_overwrites_existing(store):
    event = store.append("c1", EventType.NARRATOR_RESPONSE, {}, 0, "loc", [])
    assert event.witnessed_by == []

    ok = store.update_witnessed_by(event.id, ["Rin"])
    assert ok

    fetched = store.get_recent("c1", limit=1)[0]
    assert fetched.witnessed_by == ["Rin"]


def test_update_witnessed_by_unknown_event_returns_false(store):
    assert not store.update_witnessed_by("nonexistent-id", ["Rin"])
