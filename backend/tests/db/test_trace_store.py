import pytest
from app.db.trace_store import TraceStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_traces.db")
    store = TraceStore(db_path)
    yield store
    store.close()


def _entries():
    return [
        {
            "call": "narrator",
            "input": [
                {"title": "Scene", "body": "The tavern is quiet.\nA lantern flickers.", "truncated": False},
                {"title": "Memory", "body": "O herói lembrou-se do juramento feito à sua irmã.", "truncated": True},
            ],
            "output": "Você entra na taverna e o silêncio te recebe.\nAlguém tosse no canto escuro.",
        }
    ]


def test_append_and_get_recent_round_trip(store):
    entries = _entries()
    summary = {
        "call_count": 1,
        "total_input_tokens": 120,
        "total_output_tokens": 45,
        "total_cache_read_tokens": 10,
        "total_cache_creation_tokens": 5,
        "total_time_s": 1.23,
    }
    store.append("camp-1", action="open the door", entries=entries, summary=summary)

    recent = store.get_recent("camp-1")
    assert len(recent) == 1
    row = recent[0]
    assert row["action"] == "open the door"
    assert row["entries"] == entries
    assert row["turn_index"] == 1
    assert row["summary"]["total_input_tokens"] == 120
    assert row["summary"]["call_count"] == 1


def test_turn_index_increments(store):
    for i in range(3):
        store.append("camp-1", action=f"action {i}", entries=_entries())

    recent = store.get_recent("camp-1")
    assert [r["turn_index"] for r in recent] == [1, 2, 3]


def test_campaign_isolation(store):
    store.append("camp-a", action="a1", entries=_entries())
    store.append("camp-b", action="b1", entries=_entries())

    assert len(store.get_recent("camp-a")) == 1
    assert len(store.get_recent("camp-b")) == 1
    assert store.get_recent("camp-a")[0]["action"] == "a1"


def test_get_recent_chronological_order(store):
    for i in range(4):
        store.append("camp-1", action=f"action {i}", entries=_entries())

    recent = store.get_recent("camp-1", limit=4)
    turn_indices = [r["turn_index"] for r in recent]
    assert turn_indices == sorted(turn_indices)


def test_prune_keeps_only_recent(store):
    for i in range(5):
        store.append("camp-1", action=f"action {i}", entries=_entries(), keep=2)

    recent = store.get_recent("camp-1", limit=100)
    assert len(recent) == 2
    assert [r["turn_index"] for r in recent] == [4, 5]


def test_delete_for_campaign(store):
    store.append("camp-1", action="a1", entries=_entries())
    store.append("camp-1", action="a2", entries=_entries())
    store.append("camp-2", action="b1", entries=_entries())

    deleted = store.delete_for_campaign("camp-1")
    assert deleted == 2
    assert store.get_recent("camp-1") == []
    assert len(store.get_recent("camp-2")) == 1


def test_list_campaigns(store):
    store.append("camp-1", action="a1", entries=_entries())
    store.append("camp-1", action="a2", entries=_entries())
    store.append("camp-2", action="b1", entries=_entries())

    campaigns = {c["campaign_id"]: c["turns"] for c in store.list_campaigns()}
    assert campaigns == {"camp-1": 2, "camp-2": 1}


def test_corrupted_entries_json_falls_back_to_empty_list(store):
    store.append("camp-1", action="a1", entries=_entries())
    with store._lock:
        store._conn.execute("UPDATE llm_traces SET entries='{not json' WHERE campaign_id='camp-1'")
        store._conn.commit()

    recent = store.get_recent("camp-1")
    assert recent[0]["entries"] == []
