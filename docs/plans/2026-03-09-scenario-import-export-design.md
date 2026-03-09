# Scenario Import/Export — Design

**Date:** 2026-03-09
**Status:** Approved

## Overview

Add import/export functionality for scenarios, including story cards and campaigns, as portable `.json` files. Export is accessible from the home page scenario cards; import is accessible from the ScenarioBuilder.

## JSON Format

```json
{
  "version": "1.0",
  "exported_at": "2026-03-09T12:00:00Z",
  "scenario": {
    "title": "...",
    "description": "...",
    "tone_instructions": "...",
    "opening_narrative": "...",
    "language": "en",
    "lore_text": "..."
  },
  "story_cards": [
    { "card_type": "NPC", "name": "...", "content": {} }
  ],
  "campaigns": [
    { "player_name": "...", "created_at": "..." }
  ]
}
```

Original IDs are discarded on import; new UUIDs are generated to prevent collisions.

## API

### Export
```
GET /api/scenarios/{scenario_id}/export
Response: JSON file download
Header: Content-Disposition: attachment; filename="{title}.json"
```

### Import
```
POST /api/scenarios/import
Body: full JSON payload (scenario + story_cards + campaigns)
Response: created Scenario object (same shape as POST /scenarios/)
```

Campaigns are read via a new `get_campaigns_by_scenario(scenario_id)` method added to `scenario_store.py`.

## Frontend

### Home page (`App.jsx`)
- Download icon button on each scenario card
- Calls `exportScenario(id)` → fetches the export endpoint → triggers browser download via blob URL

### ScenarioBuilder (`ScenarioBuilder.jsx`)
- "Carregar de arquivo .json" button above the form
- File picker (`accept=".json"`) → parses JSON → pre-fills form fields from `scenario` block
- Stores `story_cards` and `campaigns` in local component state
- On submit: calls `importScenario(data)` instead of `createScenario`, sending form fields + story_cards + campaigns

### API client (`api.js`)
- `exportScenario(id)` — fetch + blob download
- `importScenario(data)` — POST to `/api/scenarios/import`
