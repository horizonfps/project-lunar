# Scenario Import/Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add import/export of scenarios (including story cards and campaigns) as portable `.json` files, with a download button on the home page and a file-load button in ScenarioBuilder.

**Architecture:** Two new FastAPI endpoints (`GET /{id}/export`, `POST /import`) handle serialization/deserialization on the backend. The frontend adds a blob-download helper in `api.js`, a download icon button per scenario card in `App.jsx`, and a file picker in `ScenarioBuilder.jsx` that pre-fills the form and stores extra data for the import endpoint.

**Tech Stack:** Python 3.11, FastAPI, SQLite (`scenario_store.py`), React 18, Zustand, Tailwind CSS.

---

### Task 1: Backend — Export endpoint (TDD)

**Files:**
- Modify: `backend/tests/api/test_routes_scenarios.py`
- Modify: `backend/app/api/routes_scenarios.py`

**Step 1: Write the failing test**

Add to `backend/tests/api/test_routes_scenarios.py`:

```python
def test_export_scenario(client):
    # Create scenario with a story card and campaign
    scenario = client.post("/api/scenarios/", json={
        "title": "Export World",
        "description": "desc",
        "tone_instructions": "gritty",
        "opening_narrative": "begin",
        "language": "en",
        "lore_text": "lots of lore",
    }).json()
    client.post(f"/api/scenarios/{scenario['id']}/story-cards", json={
        "card_type": "NPC", "name": "Aria", "content": {"age": 30},
    })
    # Export
    r = client.get(f"/api/scenarios/{scenario['id']}/export")
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "1.0"
    assert data["scenario"]["title"] == "Export World"
    assert len(data["story_cards"]) == 1
    assert data["story_cards"][0]["name"] == "Aria"
    assert isinstance(data["campaigns"], list)
    assert "exported_at" in data


def test_export_scenario_not_found(client):
    r = client.get("/api/scenarios/nonexistent/export")
    assert r.status_code == 404
```

**Step 2: Run test to verify it fails**

```bash
cd backend
pytest tests/api/test_routes_scenarios.py::test_export_scenario -v
```
Expected: FAIL with 404 or attribute error (endpoint doesn't exist yet).

**Step 3: Implement the export endpoint**

Add to `backend/app/api/routes_scenarios.py` (after the existing `get_story_cards` route):

```python
from datetime import datetime

@router.get("/{scenario_id}/export")
def export_scenario(scenario_id: str):
    with _get_store() as store:
        scenario = store.get_scenario(scenario_id)
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
        story_cards = store.get_story_cards(scenario_id)
        campaigns = store.get_campaigns(scenario_id)

    return {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "scenario": {
            "title": scenario.title,
            "description": scenario.description,
            "tone_instructions": scenario.tone_instructions,
            "opening_narrative": scenario.opening_narrative,
            "language": scenario.language,
            "lore_text": scenario.lore_text,
        },
        "story_cards": [
            {"card_type": c.card_type.value, "name": c.name, "content": c.content}
            for c in story_cards
        ],
        "campaigns": [
            {"player_name": c.player_name, "created_at": c.created_at}
            for c in campaigns
        ],
    }
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/api/test_routes_scenarios.py::test_export_scenario tests/api/test_routes_scenarios.py::test_export_scenario_not_found -v
```
Expected: both PASS.

**Step 5: Commit**

```bash
git add backend/tests/api/test_routes_scenarios.py backend/app/api/routes_scenarios.py
git commit -m "feat: add GET /scenarios/{id}/export endpoint"
```

---

### Task 2: Backend — Import endpoint (TDD)

**Files:**
- Modify: `backend/tests/api/test_routes_scenarios.py`
- Modify: `backend/app/api/routes_scenarios.py`

**Step 1: Write the failing tests**

Add to `backend/tests/api/test_routes_scenarios.py`:

```python
def test_import_scenario(client):
    payload = {
        "version": "1.0",
        "exported_at": "2026-01-01T00:00:00",
        "scenario": {
            "title": "Imported World",
            "description": "imported desc",
            "tone_instructions": "epic",
            "opening_narrative": "chapter one",
            "language": "pt-br",
            "lore_text": "ancient lore",
        },
        "story_cards": [
            {"card_type": "LOCATION", "name": "The Citadel", "content": {"size": "huge"}},
        ],
        "campaigns": [
            {"player_name": "Hero", "created_at": "2026-01-01T00:00:00"},
        ],
    }
    r = client.post("/api/scenarios/import", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Imported World"
    assert data["language"] == "pt-br"
    assert "id" in data

    # Verify story cards and campaigns were created
    scenario_id = data["id"]
    cards = client.get(f"/api/scenarios/{scenario_id}/story-cards").json()
    assert len(cards) == 1
    assert cards[0]["name"] == "The Citadel"


def test_import_scenario_missing_scenario_key(client):
    r = client.post("/api/scenarios/import", json={"version": "1.0"})
    assert r.status_code == 422
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/api/test_routes_scenarios.py::test_import_scenario -v
```
Expected: FAIL (endpoint doesn't exist).

**Step 3: Implement the import endpoint**

Add Pydantic models and the endpoint to `backend/app/api/routes_scenarios.py`:

```python
class ScenarioData(BaseModel):
    title: str
    description: str = ""
    tone_instructions: str = ""
    opening_narrative: str = ""
    language: str = "en"
    lore_text: str = ""


class StoryCardData(BaseModel):
    card_type: StoryCardType
    name: str
    content: dict = {}


class CampaignData(BaseModel):
    player_name: str
    created_at: str = ""


class ImportScenarioRequest(BaseModel):
    version: str
    scenario: ScenarioData
    story_cards: list[StoryCardData] = []
    campaigns: list[CampaignData] = []


@router.post("/import", status_code=201)
def import_scenario(req: ImportScenarioRequest):
    with _get_store() as store:
        scenario = store.create_scenario(
            title=req.scenario.title,
            description=req.scenario.description,
            tone_instructions=req.scenario.tone_instructions,
            opening_narrative=req.scenario.opening_narrative,
            language=req.scenario.language,
            lore_text=req.scenario.lore_text,
        )
        for card in req.story_cards:
            store.add_story_card(scenario.id, card.card_type, card.name, card.content)
        for campaign in req.campaigns:
            store.create_campaign(scenario.id, campaign.player_name)
    return scenario.__dict__
```

> **Important:** The `POST /import` route **must be registered before** `GET /{scenario_id}` and other parameterized routes in `routes_scenarios.py`, or FastAPI will interpret "import" as a `scenario_id`. Place it right after the `list_scenarios` route.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/api/test_routes_scenarios.py::test_import_scenario tests/api/test_routes_scenarios.py::test_import_scenario_missing_scenario_key -v
```
Expected: both PASS.

**Step 5: Run full API test suite**

```bash
pytest tests/api/test_routes_scenarios.py -v
```
Expected: all tests PASS.

**Step 6: Commit**

```bash
git add backend/tests/api/test_routes_scenarios.py backend/app/api/routes_scenarios.py
git commit -m "feat: add POST /scenarios/import endpoint"
```

---

### Task 3: Frontend — API client helpers

**Files:**
- Modify: `frontend/src/api.js`

**Step 1: Add `exportScenario` and `importScenario` to `api.js`**

Append to the end of `frontend/src/api.js`:

```javascript
export async function exportScenario(scenarioId, title) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/export`)
  if (!r.ok) throw new Error('Failed to export scenario')
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title || scenarioId}.json`
  a.click()
  URL.revokeObjectURL(url)
}

export async function importScenario(data) {
  const r = await fetch(`${BASE}/scenarios/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!r.ok) throw new Error('Failed to import scenario')
  return r.json()
}
```

**Step 2: Verify no syntax errors**

```bash
cd frontend
npx vite build 2>&1 | head -20
```
Expected: build completes or only pre-existing warnings.

**Step 3: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat: add exportScenario and importScenario API helpers"
```

---

### Task 4: Frontend — Download button on home page

**Files:**
- Modify: `frontend/src/App.jsx`

**Step 1: Import `exportScenario` and add the download button**

In `frontend/src/App.jsx`, update the import at the top:

```javascript
import { fetchScenarios, exportScenario } from './api'
```

Then, inside the scenario card `<div>` (after the `Play →` button, around line 74), add a download button alongside it. Replace the card footer area:

```jsx
<div className="flex items-center justify-between">
  <button
    onClick={() => startCampaign(s)}
    className="text-indigo-400 hover:text-indigo-300 text-sm font-medium transition-colors"
  >
    Play →
  </button>
  <button
    onClick={(e) => { e.stopPropagation(); exportScenario(s.id, s.title) }}
    title="Export scenario"
    className="text-gray-500 hover:text-gray-300 transition-colors"
  >
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
      <path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/>
      <path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/>
    </svg>
  </button>
</div>
```

**Step 2: Verify in browser**

Start the dev server:
```bash
cd frontend && npm run dev
```
Open http://localhost:5173. Confirm each scenario card shows a download icon. Click it and verify a `.json` file is downloaded with the scenario's title as filename.

**Step 3: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: add export download button to scenario cards on home page"
```

---

### Task 5: Frontend — Import button in ScenarioBuilder

**Files:**
- Modify: `frontend/src/components/ScenarioBuilder.jsx`

**Step 1: Update ScenarioBuilder**

Replace the full content of `frontend/src/components/ScenarioBuilder.jsx` with:

```jsx
import { useState, useRef } from 'react'
import { createScenario, importScenario } from '../api'

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'pt-br', label: 'Português (BR)' },
]

export default function ScenarioBuilder({ onCreated }) {
  const [form, setForm] = useState({
    title: '',
    description: '',
    tone_instructions: '',
    opening_narrative: '',
    language: 'en',
    lore_text: '',
  })
  const [importPayload, setImportPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const fileRef = useRef(null)

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const handleFileLoad = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target.result)
        if (!parsed.scenario) throw new Error('Invalid format')
        setForm({
          title: parsed.scenario.title || '',
          description: parsed.scenario.description || '',
          tone_instructions: parsed.scenario.tone_instructions || '',
          opening_narrative: parsed.scenario.opening_narrative || '',
          language: parsed.scenario.language || 'en',
          lore_text: parsed.scenario.lore_text || '',
        })
        setImportPayload(parsed)
        setError(null)
      } catch {
        setError('Invalid .json file. Could not parse scenario.')
      }
    }
    reader.readAsText(file)
    // Reset input so same file can be loaded again
    e.target.value = ''
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.title.trim()) return
    setLoading(true)
    setError(null)
    try {
      let scenario
      if (importPayload) {
        scenario = await importScenario({
          ...importPayload,
          scenario: form,
        })
      } else {
        scenario = await createScenario(form)
      }
      onCreated?.(scenario)
    } catch (err) {
      setError(
        importPayload
          ? 'Failed to import scenario. Is the backend running?'
          : 'Failed to create scenario. Is the backend running?'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 py-10 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <a href="/" className="text-indigo-400 hover:text-indigo-300 text-sm">
            ← Back to scenarios
          </a>
        </div>
        <h1 className="text-2xl font-bold text-white mb-1">Create Scenario</h1>
        <p className="text-gray-400 text-sm mb-6">
          Build a world for your story. Fill in the basics or paste a full world bible below.
        </p>

        {/* Import from file */}
        <div className="mb-8">
          <input
            ref={fileRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleFileLoad}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="text-sm text-indigo-400 hover:text-indigo-300 border border-indigo-800
                       hover:border-indigo-600 rounded-lg px-4 py-2 transition-colors"
          >
            ↑ Carregar de arquivo .json
          </button>
          {importPayload && (
            <span className="ml-3 text-xs text-green-400">Arquivo carregado — revise e salve</span>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              World Title <span className="text-red-400">*</span>
            </label>
            <input
              value={form.title}
              onChange={update('title')}
              placeholder="The Shattered Realm"
              required
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                         placeholder-gray-500 focus:outline-none focus:border-indigo-500 text-sm"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={update('description')}
              placeholder="A brief description of your world..."
              rows={2}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                         placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none text-sm"
            />
          </div>

          {/* Tone */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Tone &amp; Style Instructions
            </label>
            <textarea
              value={form.tone_instructions}
              onChange={update('tone_instructions')}
              placeholder="Dark and gritty. High mortality. NPCs have their own agendas. No happy endings guaranteed..."
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                         placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none text-sm"
            />
          </div>

          {/* Opening narrative */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Opening Narrative</label>
            <textarea
              value={form.opening_narrative}
              onChange={update('opening_narrative')}
              placeholder="The scene where the story begins. This is shown to the player before their first action..."
              rows={4}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                         placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none text-sm"
            />
          </div>

          {/* Language */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Narrative Language</label>
            <select
              value={form.language}
              onChange={update('language')}
              className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm
                         focus:outline-none focus:border-indigo-500"
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>

          {/* Lore text */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              World Lore
              <span className="ml-2 text-xs text-indigo-400 font-normal">
                AI will extract NPCs, locations, and factions automatically
              </span>
            </label>
            <textarea
              value={form.lore_text}
              onChange={update('lore_text')}
              placeholder="Paste your world bible here. The AI will read it and auto-create story cards for every named character, location, and faction it finds..."
              rows={8}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                         placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none text-sm"
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !form.title.trim()}
            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed
                       text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
          >
            {loading
              ? (importPayload ? 'Importing...' : 'Creating scenario...')
              : (importPayload ? 'Import Scenario →' : 'Create Scenario →')}
          </button>
        </form>
      </div>
    </div>
  )
}
```

**Step 2: Verify in browser**

1. Go to http://localhost:5173/create
2. Click "Carregar de arquivo .json"
3. Select a `.json` file exported in Task 4
4. Confirm all form fields are pre-filled
5. Confirm the button label changes to "Import Scenario →"
6. Submit and verify the scenario appears on the home page with all story cards

**Step 3: Commit**

```bash
git add frontend/src/components/ScenarioBuilder.jsx
git commit -m "feat: add import-from-file button in ScenarioBuilder"
```

---

### Task 6: Final verification

**Step 1: Run full backend test suite**

```bash
cd backend
pytest tests/ --ignore=tests/engines/test_graph_engine.py -v
```
Expected: all tests PASS (68 existing + 4 new = 72 total).

**Step 2: End-to-end smoke test**

1. Start backend: `cd backend && uvicorn app.main:app --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Create a scenario with story cards
4. Export it (download icon) — verify `.json` file is created
5. Open the file and confirm structure matches the design
6. Go to `/create`, load the file, review form, submit
7. Verify the imported scenario appears with its story cards

**Step 3: Commit**

```bash
git add .
git commit -m "feat: scenario import/export complete"
```
