import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENARIO_DB_PATH", str(tmp_path / "scenarios.db"))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.db"))
    monkeypatch.setenv("LLM_TRACE_DB_PATH", str(tmp_path / "traces.db"))
    from app.main import app
    return TestClient(app)


def test_get_traces_for_unknown_campaign_returns_empty_list(client):
    r = client.get("/api/game/does-not-exist/traces")
    assert r.status_code == 200
    assert r.json() == {"traces": []}


def test_delete_traces_for_unknown_campaign_returns_deleted_count(client):
    r = client.delete("/api/game/does-not-exist/traces")
    assert r.status_code == 200
    assert "deleted" in r.json()
    assert r.json()["deleted"] == 0
