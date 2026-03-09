import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.api.routes_game import _journal
from app.engines.journal_engine import JournalEntry, JournalCategory
from datetime import datetime


@pytest.mark.asyncio
async def test_get_journal_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/game/no-such-campaign/journal")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_journal_with_entries():
    _journal._journals["test-j1"] = [
        JournalEntry("test-j1", JournalCategory.DISCOVERY, "Found a cave", datetime.utcnow().isoformat()),
        JournalEntry("test-j1", JournalCategory.COMBAT, "Fought a troll", datetime.utcnow().isoformat()),
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/game/test-j1/journal")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["category"] == "DISCOVERY"
    assert data[1]["category"] == "COMBAT"
    del _journal._journals["test-j1"]


@pytest.mark.asyncio
async def test_get_journal_filter_category():
    _journal._journals["test-j2"] = [
        JournalEntry("test-j2", JournalCategory.DISCOVERY, "Found cave", datetime.utcnow().isoformat()),
        JournalEntry("test-j2", JournalCategory.COMBAT, "Fought troll", datetime.utcnow().isoformat()),
        JournalEntry("test-j2", JournalCategory.DISCOVERY, "Found map", datetime.utcnow().isoformat()),
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/game/test-j2/journal?category=DISCOVERY")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(e["category"] == "DISCOVERY" for e in data)
    del _journal._journals["test-j2"]
