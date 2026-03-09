# Journal View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose journal entries via API and display them in a slide-out sidebar during gameplay, with real-time updates via SSE and category filtering.

**Architecture:** Add a GET endpoint for journal retrieval. Modify the SSE stream to emit `journal:` events when new entries are created. Frontend gets a JournalPanel sidebar component toggled from the GameCanvas header.

**Tech Stack:** FastAPI (backend route), React + Zustand (frontend state), Tailwind CSS (lunar theme)

---

### Task 1: Backend — GET /api/game/{campaign_id}/journal

**Files:**
- Modify: `backend/app/api/routes_game.py`
- Test: `backend/tests/api/test_routes_journal.py` (create)

**Step 1: Write the failing test**

Create `backend/tests/api/test_routes_journal.py`:

```python
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
    # cleanup
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
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_routes_journal.py -v`
Expected: FAIL (404 — route doesn't exist)

**Step 3: Write the endpoint**

Add to `backend/app/api/routes_game.py` after the existing `/action` route (after line 57):

```python
from dataclasses import asdict
from app.engines.journal_engine import JournalCategory

@router.get("/{campaign_id}/journal")
async def get_journal(campaign_id: str, category: str | None = None):
    if category:
        try:
            cat = JournalCategory(category)
        except ValueError:
            return []
        entries = _journal.get_by_category(campaign_id, cat)
    else:
        entries = _journal.get_journal(campaign_id)
    return [asdict(e) for e in entries]
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_routes_journal.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add backend/tests/api/test_routes_journal.py backend/app/api/routes_game.py
git commit -m "feat: add GET /api/game/{campaign_id}/journal endpoint"
```

---

### Task 2: Backend — Emit journal SSE events during gameplay

**Files:**
- Modify: `backend/app/services/game_session.py:96`

**Step 1: Write the failing test**

Add to `backend/tests/services/test_game_session.py`:

```python
@pytest.mark.asyncio
async def test_journal_entry_emitted_as_sse():
    """Journal entries should be yielded as JSON-prefixed chunks."""
    mock_llm = AsyncMock()
    mock_narrator = AsyncMock()
    mock_narrator.detect_mode = AsyncMock(return_value=("NARRATIVE", {"narrative_time_seconds": 60}))
    mock_narrator.build_system_prompt = lambda **kw: "system"
    mock_narrator.stream_narrative = AsyncMock(return_value=async_gen(["Hello world"]))

    mock_memory = MagicMock()
    mock_memory.build_context_window = lambda cid: "ctx"

    mock_world = AsyncMock()
    mock_world.process_tick = AsyncMock(return_value=None)

    mock_journal = AsyncMock()
    mock_journal.evaluate_and_log = AsyncMock(return_value=JournalEntry(
        campaign_id="c1",
        category=JournalCategory.DISCOVERY,
        summary="Found a hidden passage.",
        created_at="2026-03-10T00:00:00",
    ))

    event_store = EventStore(":memory:")

    session = GameSession(
        campaign_id="c1",
        scenario_tone="dark",
        language="en",
        narrator=mock_narrator,
        memory=mock_memory,
        world_reactor=mock_world,
        journal=mock_journal,
        event_store=event_store,
    )

    chunks = []
    async for chunk in session.process_action("I search the wall"):
        chunks.append(chunk)

    journal_chunks = [c for c in chunks if c.startswith("[JOURNAL]")]
    assert len(journal_chunks) == 1
    import json
    data = json.loads(journal_chunks[0].replace("[JOURNAL]", ""))
    assert data["category"] == "DISCOVERY"
    assert data["summary"] == "Found a hidden passage."
```

Note: The test file likely already has helper fixtures. The `async_gen` helper and `JournalEntry`/`JournalCategory` imports may need to be added. Check existing test file for patterns and adapt.

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_game_session.py::test_journal_entry_emitted_as_sse -v`
Expected: FAIL (no `[JOURNAL]` chunk yielded)

**Step 3: Modify game_session.py**

In `backend/app/services/game_session.py`, change line 96 from:

```python
        await self._journal.evaluate_and_log(self.campaign_id, full_response)
```

to:

```python
        import json as _json
        entry = await self._journal.evaluate_and_log(self.campaign_id, full_response)
        if entry:
            yield f"[JOURNAL]{_json.dumps({'category': entry.category.value, 'summary': entry.summary, 'created_at': entry.created_at})}"
```

Also add the `from dataclasses import asdict` import at the top if not present. Actually the JSON dict is built manually above, so no extra import needed beyond `json`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/services/test_game_session.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/services/game_session.py backend/tests/services/test_game_session.py
git commit -m "feat: emit journal entries as SSE events during gameplay"
```

---

### Task 3: Frontend — API client + SSE journal parsing

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/store.js`

**Step 1: Add fetchJournal to api.js**

Add after the `importScenario` function (after line 91):

```javascript
export async function fetchJournal(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/journal`)
  if (!r.ok) throw new Error('Failed to fetch journal')
  return r.json()
}
```

**Step 2: Parse journal SSE events in streamAction**

In `frontend/src/api.js`, modify the `streamAction` function. The `onChunk` callback currently receives all data. Add an `onJournal` callback parameter. Change the function signature (line 35) and the SSE parsing (lines 55-61):

```javascript
export function streamAction({ campaignId, scenarioTone, language, action, onChunk, onJournal, onDone, onError }) {
```

And inside the SSE loop, before calling `onChunk(data)`:

```javascript
          if (data.startsWith('[JOURNAL]')) {
            try {
              const entry = JSON.parse(data.slice(9))
              onJournal?.(entry)
            } catch {}
            continue
          }
```

**Step 3: Add clearJournal action to store.js**

In `frontend/src/store.js`, add after line 46 (`addJournalEntry`):

```javascript
  setJournal: (journal) => set({ journal }),
```

**Step 4: Verify manually** (no automated frontend tests in this project)

Run: `cd frontend && npm run dev` — verify no build errors.

**Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/store.js
git commit -m "feat: add journal API client and SSE journal event parsing"
```

---

### Task 4: Frontend — JournalPanel component

**Files:**
- Create: `frontend/src/components/JournalPanel.jsx`

**Step 1: Create the component**

```jsx
import { useState } from 'react'

const CATEGORIES = [
  { id: null, label: 'All' },
  { id: 'DISCOVERY', label: 'Discovery' },
  { id: 'COMBAT', label: 'Combat' },
  { id: 'DECISION', label: 'Decision' },
  { id: 'RELATIONSHIP_CHANGE', label: 'Relationship' },
  { id: 'WORLD_EVENT', label: 'World' },
]

const CATEGORY_COLORS = {
  DISCOVERY: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
  COMBAT: 'text-rose-400 bg-rose-400/10 border-rose-400/30',
  DECISION: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/30',
  RELATIONSHIP_CHANGE: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  WORLD_EVENT: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
}

export default function JournalPanel({ entries, onClose }) {
  const [filter, setFilter] = useState(null)

  const filtered = filter
    ? entries.filter((e) => e.category === filter)
    : entries

  return (
    <div className="flex flex-col h-full bg-lunar-950/95 backdrop-blur-2xl border-l border-white/5">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
        <h2 className="text-white font-bold text-sm uppercase tracking-widest">Mission Log</h2>
        <button
          onClick={onClose}
          className="text-lunar-400 hover:text-white transition-colors text-xs uppercase tracking-wider"
        >
          Close
        </button>
      </div>

      {/* Category filters */}
      <div className="flex gap-1.5 px-5 py-3 overflow-x-auto border-b border-white/5">
        {CATEGORIES.map((c) => (
          <button
            key={c.id ?? 'all'}
            onClick={() => setFilter(c.id)}
            className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest whitespace-nowrap transition-all
              ${filter === c.id
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/50'
                : 'text-lunar-500 hover:text-lunar-300 hover:bg-white/5 border border-transparent'
              }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Entries */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-3">
        {filtered.length === 0 ? (
          <p className="text-lunar-500 text-sm font-light text-center mt-8">No entries recorded.</p>
        ) : (
          [...filtered].reverse().map((entry, i) => (
            <div key={i} className="p-3.5 rounded-xl bg-lunar-900/40 border border-white/5">
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded border ${CATEGORY_COLORS[entry.category] || 'text-lunar-400 bg-lunar-400/10 border-lunar-400/30'}`}>
                  {entry.category.replace('_', ' ')}
                </span>
                <span className="text-[10px] text-lunar-500 font-mono">
                  {entry.created_at?.slice(11, 19) || ''}
                </span>
              </div>
              <p className="text-lunar-100 text-sm font-light leading-relaxed">
                {entry.summary}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
```

**Step 2: Verify no build errors**

Run: `cd frontend && npm run dev`

**Step 3: Commit**

```bash
git add frontend/src/components/JournalPanel.jsx
git commit -m "feat: add JournalPanel component with category filters"
```

---

### Task 5: Frontend — Wire JournalPanel into GameCanvas

**Files:**
- Modify: `frontend/src/components/GameCanvas.jsx`

**Step 1: Add journal state, toggle, SSE handler, and panel**

In `GameCanvas.jsx`:

1. Import JournalPanel and fetchJournal:
```jsx
import { useState } from 'react'  // add useState to existing import
import JournalPanel from './JournalPanel'
import { streamAction, fetchJournal } from '../api'
```

2. Add to the store destructure: `journal`, `addJournalEntry`, `setJournal`

3. Add local state for panel visibility:
```jsx
const [journalOpen, setJournalOpen] = useState(false)
```

4. Add journal load on toggle:
```jsx
const toggleJournal = async () => {
  if (!journalOpen && activeCampaignId) {
    try {
      const entries = await fetchJournal(activeCampaignId)
      setJournal(entries)
    } catch {}
  }
  setJournalOpen(!journalOpen)
}
```

5. Update `handleAction` to pass `onJournal: addJournalEntry` to `streamAction`

6. Add toggle button in header (next to Disconnect):
```jsx
<button
  onClick={toggleJournal}
  className={`px-4 py-2 rounded-lg text-xs font-semibold uppercase tracking-wider transition-colors border
    ${journalOpen
      ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/50'
      : 'bg-white/5 hover:bg-white/10 text-lunar-300 border-white/5'
    }`}
>
  Log{journal.length > 0 ? ` (${journal.length})` : ''}
</button>
```

7. Wrap message feed + journal panel in a flex row:
- The message feed div gets `flex-1`
- JournalPanel renders conditionally in a `w-80` container on the right side

**Step 2: Verify manually**

Run: `cd frontend && npm run dev` — open GameCanvas, toggle journal sidebar, verify it slides in.

**Step 3: Commit**

```bash
git add frontend/src/components/GameCanvas.jsx
git commit -m "feat: wire JournalPanel into GameCanvas with real-time SSE updates"
```

---

### Task 6: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Step 1: Mark Journal View as complete in Feature Backlog**

Change `- [ ] **Journal View**` to `- [x] **Journal View**` and add brief note.

**Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: mark Journal View feature as complete"
```
