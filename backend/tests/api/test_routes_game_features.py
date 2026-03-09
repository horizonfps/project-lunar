import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from types import SimpleNamespace


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENARIO_DB_PATH", str(tmp_path / "scenarios.db"))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.db"))
    from app.main import app
    return TestClient(app)


def test_get_settings(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "provider" in data
    assert "model" in data
    assert "temperature" in data
    assert "max_tokens" in data


def test_update_settings(client):
    r = client.post("/api/settings", json={
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.5,
        "max_tokens": 4096,
    })
    assert r.status_code == 200
    assert r.json()["provider"] == "openai"
    assert r.json()["model"] == "gpt-4o"

    # Verify it persisted
    r2 = client.get("/api/settings")
    assert r2.json()["provider"] == "openai"
    assert r2.json()["temperature"] == 0.5


def test_update_settings_invalid_provider_falls_back(client):
    r = client.post("/api/settings", json={
        "provider": "invalid_provider",
        "model": "some-model",
    })
    assert r.status_code == 200
    assert r.json()["provider"] == "deepseek"


def test_get_npc_minds_empty(client):
    r = client.get("/api/game/test-campaign/npc-minds")
    assert r.status_code == 200
    assert r.json() == []


def test_get_memory_crystals_empty(client):
    r = client.get("/api/game/test-campaign/memory-crystals")
    assert r.status_code == 200
    assert r.json() == []


def test_timeskip_logs_world_changes_in_journal(client, monkeypatch):
    from app.api import routes_game

    async def fake_process_tick(campaign_id, narrative_seconds, world_context):
        return "Factions shift in the capital."

    journal_spy = AsyncMock(return_value=None)
    monkeypatch.setattr(routes_game._world_reactor, "process_tick", fake_process_tick)
    monkeypatch.setattr(routes_game._journal, "evaluate_and_log", journal_spy)

    r = client.post("/api/game/camp-timeskip/timeskip", json={"seconds": 86400})
    assert r.status_code == 200
    assert "summary" in r.json()
    journal_spy.assert_awaited_once_with("camp-timeskip", "Factions shift in the capital.")


def test_graph_search_falls_back_to_world_graph(client, monkeypatch):
    from app.api import routes_game

    class DummyGraphiti:
        async def search(self, campaign_id, query):  # pragma: no cover - simple test stub
            return []

    class DummyGraph:
        async def initialize(self):
            return None

        async def get_all_nodes(self):
            return [
                SimpleNamespace(
                    id="n1",
                    name="Lady Seraphine",
                    node_type=SimpleNamespace(value="NPC"),
                    attributes={"title": "Leader of the Moonsworn"},
                ),
                SimpleNamespace(
                    id="n2",
                    name="Moonsworn Rebellion",
                    node_type=SimpleNamespace(value="FACTION"),
                    attributes={},
                ),
            ]

        async def get_all_relationships(self):
            return [{"source_id": "n1", "target_id": "n2", "rel_type": "LEADS", "strength": 1.0}]

    monkeypatch.setattr(routes_game, "_get_graphiti_engine", lambda: DummyGraphiti())
    monkeypatch.setattr(routes_game, "_get_graph_engine", lambda campaign_id: DummyGraph())

    r = client.get("/api/game/camp-search/graph-search?q=Seraphine")
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert len(facts) >= 1
    assert any("Seraphine" in f["fact"] for f in facts)
