import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENARIO_DB_PATH", str(tmp_path / "scenarios.db"))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.db"))
    from app.main import app
    return TestClient(app)


def test_world_graph_endpoint(client):
    r = client.get("/api/game/test-campaign/world-graph")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "links" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["links"], list)


def test_graph_search_endpoint(client):
    r = client.get("/api/game/camp-1/graph-search?q=who+is+the+knight")
    assert r.status_code == 200
    data = r.json()
    assert "facts" in data
    assert isinstance(data["facts"], list)
