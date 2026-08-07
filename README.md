<p align="center">
  <img src="docs/banner.png" alt="Project Lunar" width="100%" />
</p>

<p align="center">
  <strong>An open-source storytelling engine where every choice reshapes the world.</strong><br>
  <sub>Authors build worlds. Players live adventures. AI narrates everything — bilingually, with memory that never forgets.</sub>
</p>

<p align="center">
  <a href="#features">Features</a> &middot;
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#scenarios--setup-wizard">Scenarios</a> &middot;
  <a href="#memory-system">Memory</a> &middot;
  <a href="#combat-system">Combat</a> &middot;
  <a href="#llm-providers">LLM Providers</a> &middot;
  <a href="#claude-max-proxy-optional">Proxy</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

---

## What is Project Lunar?

Project Lunar is a **local-first** narrative RPG **engine**, not a single game. Authors build scenarios — fantasy, sci-fi, modern, slice-of-life, anything — with lore, NPCs, locations, factions and a setup wizard. Players live through dynamically generated adventures narrated by LLMs with persistent multi-tier memory, a reactive world, creativity-based combat, and AI-generated cold-opens that respond to who you choose to be.

No HP bars. No mana pools. No grinding. Just **storytelling** — in English or Brazilian Portuguese.

---

## Features

| | Feature | Description |
|---|---------|-------------|
| **Scenarios** | Setup Wizard | Authors define questions with text/choice fields; players answer at campaign start. Answers interpolate into lore via `{{variable}}` syntax |
| **Openings** | AI-Generated Cold Opens | Set `opening_mode: ai` and the narrator writes a unique 180-320 word opening per campaign, weaving in the player's setup answers |
| **Narrator** | Mode-Aware Engine | Switches between Narrative, Combat, and Meta modes with real-time SSE streaming |
| **Memory** | 4-Tier Crystal Pyramid | SHORT → MEDIUM → LONG → MEMORY. Auto-crystallizes every 4 actions with strict name-preservation and witness filtering |
| **World** | Reactive World | Off-screen world evolves proportionally to in-narrative time elapsed |
| **Combat** | Creativity-Based + Power Levels | No stats — actions scored on coherence, creativity, context. LLM evaluates player vs. opponent power using story card NPCs as anchors. Toggle on/off per campaign |
| **NPCs** | Independent Minds | Each NPC tracks private feeling, goal, opinion_of_player, secret_plan. Fuzzy dedup with LLM confirmation. Witnessed-by filter prevents NPCs from "knowing" off-screen events |
| **Graph** | Knowledge Graph | Neo4j-powered entity tracking with relationship extraction and canonical name resolution |
| **Journal** | Auto-Detection | AI identifies significant events (discoveries, relationship changes, combat, decisions) and logs them |
| **Plots** | Auto-Plot Generator | Macro story arcs, micro-hooks, and NPC generation on dynamic cooldowns with plot lock system |
| **Inventory** | Item Lifecycle | Narrative-driven via inline tags `[ITEM_ADD]`, `[ITEM_USE]`, `[ITEM_LOSE]` parsed from LLM output |
| **Rewind** | Undo System | Rewind last action to explore different story branches |
| **Bilingual** | en + pt-br | Every system prompt, crystal, journal entry and tag is language-aware |
| **RAG** | Dynamic Story Cards | Story cards selected by keyword overlap with recent context instead of dumping everything |
| **Multi-LLM** | Runtime Switching | DeepSeek V4 (1M ctx), Anthropic Sonnet/Opus 4.6 (1M ctx), OpenAI GPT-5.6 Sol — switch in Settings, no restart |
| **Persistence** | Survives Restarts | All in-memory state (NPC minds, plot seeds, crystals, inventory) is rebuilt from the event store on every GET |

---

## Quickstart

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **Docker** (for Neo4j)
- An LLM API key: **DeepSeek** ([get one](https://platform.deepseek.com/)), **Anthropic**, or **OpenAI** — or a Claude Pro/Max subscription via the proxy

### Install & Run

```bash
# Clone
git clone https://github.com/horizonfps/project-lunar.git
cd project-lunar

# One-command setup
./install.sh          # Linux/macOS
# install.bat         # Windows

# Configure
cp .env.example .env
# Edit .env → add your API key(s)

# Start everything (Windows)
start.bat             # Starts Neo4j, optional proxy, backend, frontend

# Or start manually:
docker-compose up -d neo4j
cd backend && source venv/bin/activate
uvicorn app.main:app --reload --port 8000
# in another terminal:
cd frontend && npm run dev
```

Open **http://localhost:5173** and start your adventure.

### Configuration

```env
# LLM Providers (at least one required)
DEEPSEEK_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Neo4j (matches docker-compose)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=lunar_password

# Optional: CLIProxyAPI (see Proxy section)
ANTHROPIC_PROXY_URL=http://127.0.0.1:8318
ANTHROPIC_PROXY_KEY=lunar-proxy-key
OPENAI_PROXY_URL=http://127.0.0.1:8318/v1
OPENAI_PROXY_KEY=lunar-proxy-key

# Optional: debug logging
DEBUG=false
```

Switch providers at runtime in the **Settings** panel — no restart needed. Settings are per-campaign and persist across sessions.

---

## How to Play

1. **Create a Scenario** — In the builder, fill in title, language, tone instructions, and **setup questions**. Choose `opening_mode`: a `fixed` written opening, or `ai` to let the engine write one per campaign using the player's setup answers.
2. **Create a Campaign** — Pick a scenario, answer its setup wizard, optionally toggle combat off. If `opening_mode == ai`, the engine writes a custom cold-open right then.
3. **Act** — Use the action selector:
   - **DO** — Perform a physical action
   - **SAY** — Speak in character (text appears verbatim before NPC reactions)
   - **CONTINUE** — Let the story flow
   - **META** — Ask the narrator out-of-character questions about the world state
4. **Mention NPCs** with `@` autocomplete — names always render as `@Full Name` in narration for consistency.
5. **Explore** — Open panels for inventory, world map, NPC minds, journal, memory crystals, and plot generation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React 19)                      │
│  GameCanvas · ActionInput · SettingsPanel · WorldMapModal       │
│  NpcInspector · JournalPanel · InventoryPanel · MemoryInspector │
│  PlotGeneratorPanel · ScenarioBuilder · SetupWizard             │
└────────────────────────────┬────────────────────────────────────┘
                             │ SSE / REST
┌────────────────────────────▼────────────────────────────────────┐
│                     FastAPI Backend                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                GameSession (orchestrator, 2.7k loc)      │   │
│  │  process_action() → detect_mode → narrate → side effects │   │
│  └────┬─────┬─────┬─────┬─────┬──────┬─────┬─────┬─────┬────┘   │
│       │     │     │     │     │      │     │     │     │        │
│  Narrator Memory Combat NPC  Journal Graph World Plot  Opening  │
│  Engine  Engine  Engine Mind Engine  Engine Reac. Gen. Gen.     │
│       │     │     │     │     │      │     │     │     │        │
│  ┌────▼─────▼─────▼─────▼─────▼──────▼─────▼─────▼─────▼───┐    │
│  │       LLM Router (litellm) + token forensic dump        │    │
│  │  DeepSeek V4 · Anthropic Claude 4.6 · OpenAI GPT-5.6 Sol    │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ EventStore (SQL) │  │ ScenarioStore    │                     │
│  │ Append-only log  │  │ Scenarios +      │                     │
│  │ events.db        │  │ Campaigns +      │                     │
│  │                  │  │ StoryCards +     │                     │
│  │                  │  │ SetupAnswers     │                     │
│  └──────────────────┘  └──────────────────┘                     │
└────────────────────────────────────┬────────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   Neo4j (Docker)    │
                          │   Knowledge Graph   │
                          └─────────────────────┘
```

### Engine Breakdown

| Engine | Purpose | Key Behavior |
|--------|---------|-------------|
| **NarratorEngine** | Mode detection, prompt building, streaming | Builds multi-section system prompts; dynamic history window scaled to provider context (200/600 msgs cap on 200k/1M models); JSON single-call mode for cache-enabled providers |
| **MemoryEngine** | 4-tier crystallization | SHORT (4 actions) → MEDIUM (4 SHORTs) → LONG (4 MEDIUMs) → MEMORY (permanent). Strict name preservation. Witness filter so NPC-specific facts aren't leaked across perspectives |
| **CombatEngine** | Creativity-scored combat | Scores coherence / creativity / context (40/40/20). Anti-griefing rejects meta-gaming. Dynamic power-level evaluation calibrated against story card NPC anchors |
| **NpcMindEngine** | NPC inner thoughts | Tracks feeling, goal, opinion_of_player, secret_plan. Fuzzy name dedup with LLM confirmation. Skips dead / merely-mentioned NPCs |
| **JournalEngine** | Auto-event detection | Categories: DISCOVERY, RELATIONSHIP_CHANGE, COMBAT, DECISION, WORLD_EVENT. Respects scenario language |
| **GraphEngine** | Neo4j entity graph | Node types: NPC, LOCATION, FACTION, ITEM, EVENT. Canonical name resolution |
| **WorldReactor** | Off-screen world changes | Tick types scaled by time: MICRO (<1h, no change) → HEAVY (>1 month, wars/deaths) |
| **PlotGenerator** | Auto story elements | Macro arcs, micro-hooks, NPC seeds with cooldown + plot-lock so only one runs at a time |
| **InventoryEngine** | Item lifecycle | Carried / used / lost, parsed from inline `[ITEM_ADD\|USE\|LOSE]` tags |
| **OpeningGenerator** | One-shot AI cold-opens | 180-320 word opening per campaign when `opening_mode == ai`, weaving setup answers + tone |
| **LLMRouter** | Multi-provider abstraction | litellm wrapper with primary/fallback, Anthropic proxy routing, per-call token tracking, optional forensic dump to `logs/llm_calls/*.json` (set `LUNAR_DUMP_LLM_CALLS=1`) |

---

## Scenarios & Setup Wizard

Scenarios are first-class objects with rich authoring features:

```python
Scenario(
    id, title, description,
    tone_instructions,        # Writing style + narrative rules
    opening_narrative,        # Used when opening_mode == "fixed"
    language,                 # "en" | "pt-br"
    lore_text,                # Free-form text — AI extracts NPCs/locations/factions
    setup_questions = [       # NEW: authored by scenario creators
        {
            "var_name": "main_clan",
            "prompt": "Which clan does {{character_name}} belong to?",
            "type": "choice",
            "options": [
                {"label": "Iron Wolves", "description": "Northern raiders..."},
                {"label": "Sky Heralds",  "description": "Sun-priests..."},
            ],
            "required": True,
        },
        {"var_name": "starting_fear", "prompt": "What does your character fear most?", "type": "text"},
    ],
    opening_mode = "ai",      # "fixed" or "ai"
    ai_opening_directive = "Open in medias res, mid-conversation. End on a choice.",
)
```

Setup answers are persisted per campaign, interpolated into tone/lore/opening with `{{var_name}}` syntax, and rendered as a `CHARACTER SETUP` block in every system prompt so the LLM always knows who the player is.

**Story Cards** — NPCs, locations, factions, items, lore fragments — are stored separately and selected dynamically per turn by keyword overlap with recent context (RAG), instead of dumping the entire library every action.

---

## Memory System

Project Lunar uses a **4-tier crystal pyramid** so the AI never forgets, even in 200+ action campaigns:

```
Action  1- 4: [SHORT_1: actions 1-4]
Action  5- 8: [SHORT_2: actions 5-8]
Action  9-12: [SHORT_3: actions 9-12]
Action 13-16: [SHORT_4: actions 13-16] → consolidate → MEDIUM_1 (actions 1-16)
…
4 MEDIUMs   → LONG    (~64 actions, one full story arc)
4 LONGs     → MEMORY  (permanent canonical world facts)
```

**What the LLM sees at action 100 on a 1M-context model:**
- A few MEMORY-tier crystals (permanent identity, completed arcs, world facts)
- The current LONG crystal (active arc summary)
- All MEDIUM crystals between the active LONG and now
- All unconsolidated SHORTs
- Up to 600 raw conversation messages (200 on 200k models)
- Current NPC thoughts, latest journal entries, RAG-selected story cards
- Neo4j relationship snapshot

**Crystal schema (structured JSON, not freeform text):**

```json
{
  "ai": {
    "events":   [{"who": "...", "action": "...", "where": "...", "result": "..."}],
    "characters": { "<Name>": {"description": "...", "state": "...", "relationship_to_player": "..."} },
    "items":    [{"name": "...", "owner": "...", "status": "acquired|used|lost"}],
    "promises_or_missions": ["<verbatim text>"],
    "world_facts": ["<lasting facts>"]
  },
  "summary": "<short player-facing text>"
}
```

**Integrity rules enforced at every tier**: proper names are preserved exactly (no substituting "Lena" with "Lana" or similar canonical names from pop fiction), physical descriptions are kept verbatim, open promises survive consolidation until explicitly resolved.

**Witness filter**: each crystal tracks which NPCs witnessed its source events; NPC-specific facts won't leak to characters who weren't there. MEMORY tier is global canon and ignores this filter.

---

## Combat System

Project Lunar uses a **creativity-based combat system** — no HP, mana, or levels — with an optional **dynamic power scale**.

### Action scoring

Every action is evaluated on three axes:

| Axis | Weight | Description |
|------|--------|-------------|
| **Coherence** | 40% | Does the action make physical/logical sense? |
| **Creativity** | 40% | Is it original and unexpected? |
| **Context** | 20% | Does it use the environment and narrative? |

| Outcome | Trigger | Effect |
|---------|---------|--------|
| Critical Success | High quality + luck | Spectacular success + 1 free action |
| Success | quality × 0.65 + (1-difficulty) × 0.35 | Action succeeds as intended |
| Fail | Below threshold | Action fails (enforced — the narrator cannot ignore the dice roll) |
| Critical Fail | Low quality + bad luck | Action backfires — NPC gains +2 actions |

Anti-griefing rejects meta-gaming ("I kill everyone instantly") and physically impossible actions.

### Power-level evaluation

When combat starts, the engine asks the LLM to rate the opponent's power 1–10. If the scenario provides a **WORLD POWER SCALE** (built from story card NPCs as anchors — top 25 + bottom 25), the model calibrates the opponent relative to that scale. Player power is evaluated the same way and persisted. This makes combat consistent across scenarios — a "tier-1 swordsman" stays tier-1 whether the world is shōnen, sword-and-sorcery, or post-apocalyptic.

### Per-campaign toggle

Each campaign has a `combat_enabled` flag. Disable it for purely narrative campaigns; the mode detector will never route to COMBAT mode and the system prompt skips all combat rules.

---

## LLM Providers

Project Lunar supports multiple LLM providers via [litellm](https://github.com/BerriAI/litellm). Switch providers at runtime in the Settings panel.

| Provider | Models | Context | Notes |
|----------|--------|---------|-------|
| **DeepSeek** | deepseek-v4-flash, deepseek-v4-pro | 1M | Streaming, lowest cost/quality ratio |
| **Anthropic** | claude-sonnet-4-6, claude-opus-4-6 | 1M | Single-call mode + prompt caching |
| **Anthropic** | claude-haiku-4-5, claude-sonnet-4-5, claude-opus-4-5 | 200K | Via API key or Max proxy |
| **OpenAI** | gpt-5.6-sol | 372K | CLIProxyAPI, single-chunk streaming |

The **context window is detected automatically** per model and used to size the history slice, RAG selection, and crystal injection budget. There are no hardcoded character caps — the project targets full utilization of the model's context.

### Provider Quality (qualitative, from extended playtesting)

**DeepSeek — Best Value 🏆**
Light-novel prose, vivid emotions, strong scenario adherence. Recent cost optimization cut DeepSeek per-action cost by ~87%. Best daily driver for long campaigns.

**Anthropic (Claude) — Best Quality 👑**
Literary fiction. Deepest character work, layered subtext, best instruction adherence. Single-call mode + prompt caching keeps long sessions affordable on Sonnet. Use via API key or the Claude Max Proxy below.

**OpenAI (GPT) — Not Recommended ⚠️**
Looks good in short sessions but degrades over time, falling into repetitive narrative patterns and ignoring custom narrator rules.

### Temperature

Default is **1.5** — empirically the sweet spot for DeepSeek narrative work. Anthropic tolerates 0.9–1.0 well. The router omits temperature for `gpt-5.6-sol`. Tunable per session in Settings.

---

## Project Structure

```
project-lunar/
├── backend/
│   └── app/
│       ├── api/
│       │   ├── routes_game.py        # 23 endpoints: action, state, memory, journal, etc.
│       │   └── routes_scenarios.py   # CRUD + import/export + preview-opening
│       ├── db/
│       │   ├── event_store.py        # Append-only event log (SQLite)
│       │   └── scenario_store.py     # Scenarios, story cards, campaigns, setup answers
│       ├── engines/
│       │   ├── narrator_engine.py        # Mode detection, prompts, streaming, single-call
│       │   ├── memory_engine.py          # 4-tier crystallization (1k loc)
│       │   ├── combat_engine.py          # Creativity scoring + power levels
│       │   ├── npc_mind_engine.py        # NPC thoughts + fuzzy dedup
│       │   ├── journal_engine.py         # Auto-event detection
│       │   ├── graph_engine.py           # Neo4j knowledge graph
│       │   ├── graphiti_engine.py        # Temporal knowledge graph (experimental)
│       │   ├── world_reactor.py          # Off-screen world evolution
│       │   ├── plot_generator.py         # Auto-plot (arcs, hooks, NPCs)
│       │   ├── inventory_engine.py       # Item lifecycle
│       │   ├── opening_generator.py      # AI cold-open writer
│       │   └── llm_router.py             # Multi-provider router + token tracker
│       ├── services/
│       │   ├── game_session.py           # Main orchestrator (2.7k loc)
│       │   ├── scenario_service.py       # Scenario management
│       │   └── scenario_interpolation.py # {{var}} substitution
│       ├── utils/                  # JSON parsing helpers
│       ├── config.py               # Pydantic settings + .env
│       └── main.py                 # FastAPI entry point + /api/settings
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── GameCanvas.jsx           # Main gameplay UI + SSE handler
│       │   ├── ActionInput.jsx          # DO/SAY/CONTINUE/META + @-mention autocomplete
│       │   ├── CombatOverlay.jsx        # Combat mode UI
│       │   ├── SettingsPanel.jsx        # Provider/model/temperature/max_tokens
│       │   ├── InventoryPanel.jsx
│       │   ├── JournalPanel.jsx
│       │   ├── WorldMapModal.jsx        # Force-graph Neo4j visualization
│       │   ├── MemoryInspector.jsx      # Crystal viewer (all 4 tiers)
│       │   ├── NpcInspector.jsx         # NPC thought browser
│       │   ├── PlotGeneratorPanel.jsx   # On-demand generation
│       │   ├── TimeskipModal.jsx        # Manual time advancement
│       │   ├── ScenarioBuilder.jsx      # World creation + lore extraction
│       │   ├── SetupWizard.jsx          # Pre-game question flow
│       │   └── ErrorBoundary.jsx
│       ├── lib/                      # interpolate helper, etc.
│       ├── store.js                  # Zustand state management
│       ├── api.js                    # REST + SSE API helpers
│       └── App.jsx                   # Routes (/, /create, /play)
├── proxy/
│   ├── cliproxyapi/                # CLIProxyAPI (Go binary, recommended)
│   │   ├── config.yaml                # Proxy config (port 8318, API key)
│   │   └── cli-proxy-api.exe          # Binary (downloaded, .gitignored)
│   ├── auth.py / server.py / run.py # Legacy OAuth proxy (Haiku-only)
│   └── README.md                   # Proxy documentation
├── docker-compose.yml              # Neo4j container
├── .env.example
├── install.sh / install.bat        # One-command setup
└── start.bat                       # Windows: brings up Neo4j + proxy + backend + frontend
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 · Vite 7 · Zustand 5 · Tailwind 3 · Framer Motion · react-force-graph-2d · react-markdown · Lucide |
| Backend | Python 3.10+ · FastAPI · pydantic-settings · SQLite (event sourcing) |
| Knowledge Graph | Neo4j 5 (Docker) · Graphiti-core (temporal, experimental) |
| LLM | litellm (DeepSeek · Anthropic · OpenAI) · instructor · tiktoken |
| Bilingual | Native en + pt-br across every prompt, crystal, and tag |

---

## API Reference

All endpoints are versioned under `/api/`. Game endpoints are scoped to a campaign.

### Game (`/api/game`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/action` | Stream a player action (SSE) |
| GET | `/{campaign_id}/scenario-view` | Resolved scenario tone + lore + opening (after interpolation) |
| GET | `/{campaign_id}/setup-state` | Setup questions + saved answers |
| POST | `/{campaign_id}/setup-answers` | Save player's setup wizard answers |
| POST | `/{campaign_id}/regenerate-opening` | Re-roll the AI cold-open |
| PATCH | `/{campaign_id}/settings` | Toggle `combat_enabled`, etc. |
| GET | `/{campaign_id}/history` | Full conversation log |
| POST | `/{campaign_id}/rewind` | Undo last action |
| POST | `/{campaign_id}/timeskip` | Advance narrative time manually |
| GET | `/{campaign_id}/journal` | Journal entries |
| GET | `/{campaign_id}/npc-minds` | All NPC inner-thought states |
| PUT/DELETE | `/{campaign_id}/npc-minds/{name}` | Edit / delete an NPC mind |
| GET | `/{campaign_id}/characters` | Player + NPC roster |
| GET | `/{campaign_id}/memory-crystals` | All 4-tier crystals |
| POST | `/{campaign_id}/crystallize` | Manually trigger consolidation |
| POST | `/{campaign_id}/generate` | Generate NPC / event / plot on demand |
| POST | `/{campaign_id}/inject-npc-seed` | Pre-seed an NPC for the next scene |
| GET | `/{campaign_id}/inventory` | Player inventory |
| POST | `/{campaign_id}/inventory` | Manual item add/remove |
| GET | `/{campaign_id}/graph-search?q=...` | Search the Neo4j graph |
| GET | `/{campaign_id}/world-graph` | Graph snapshot for the map |

### Scenarios (`/api/scenarios`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all scenarios |
| POST | `/` | Create scenario |
| POST | `/preview-opening` | Test an AI opening without saving |
| POST | `/import` | Import from JSON |
| GET | `/{id}` | Fetch scenario |
| GET | `/{id}/export` | Export as JSON |
| POST | `/{id}/story-cards` | Add NPC/Location/Faction/Item/Lore card |
| GET | `/{id}/story-cards` | List cards |
| POST | `/{id}/campaigns` | Create campaign |
| GET | `/{id}/campaigns` | List campaigns |
| DELETE | `/{id}/campaigns/{campaign_id}` | Delete campaign |
| DELETE | `/{id}` | Delete scenario |

### Settings & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Current global LLM config |
| POST | `/api/settings` | Update provider / model / temperature / max_tokens |
| GET | `/api/health` | Liveness probe |
| GET | `/api/health/neo4j` | Neo4j connectivity check |

---

## CLIProxyAPI Subscription Proxy (Optional)

CLIProxyAPI can route Anthropic and OpenAI calls through authenticated subscriptions. Project Lunar supports the Anthropic `/v1/messages` endpoint and the OpenAI-compatible `/v1/chat/completions` endpoint.

### How it works

The proxy uses [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), a Go binary that handles OAuth, token refresh, and provider protocol translation. The backend reads `ANTHROPIC_PROXY_URL` and `OPENAI_PROXY_URL` independently and routes each provider through its configured local endpoint. Proxy calls use the non-streaming compatibility path and are delivered to the frontend as a single chunk.

> CLIProxyAPI is a pre-compiled Go binary (not built from source here) because it handles the OAuth flow, token refresh, and Claude Code protocol translation. The binary is `.gitignore`d; you download it during setup.

### Setup

```bash
# 1. Download CLIProxyAPI (one-time)
cd proxy/cliproxyapi
# Download from: https://github.com/router-for-me/CLIProxyAPI/releases/latest
# Extract cli-proxy-api.exe (Windows) or cli-proxy-api (Linux/macOS) into this folder

# 2. Authenticate providers that are not already configured
./cli-proxy-api.exe -claude-login -config config.yaml
./cli-proxy-api.exe -codex-login -config config.yaml

# 3. Start the proxy
./cli-proxy-api.exe -config config.yaml
# Proxy runs on http://127.0.0.1:8318 (configured in config.yaml)
```

On Windows, `start.bat` will auto-start the proxy if `cli-proxy-api.exe` is present in `proxy/cliproxyapi/`.

### Configure .env

```env
ANTHROPIC_PROXY_URL=http://127.0.0.1:8318
ANTHROPIC_PROXY_KEY=lunar-proxy-key
OPENAI_PROXY_URL=http://127.0.0.1:8318/v1
OPENAI_PROXY_KEY=lunar-proxy-key
```

An already-running CLIProxyAPI can use a different port and key in the local `.env`. Then select Anthropic or OpenAI in the Settings panel and play.

### Reliability

The router retries transient proxy failures (0.5s + 1.5s backoff, 3 total attempts) so a single hiccup never leaks the English fallback string into a non-English campaign.

See [`proxy/README.md`](proxy/README.md) for detailed setup, troubleshooting, and legacy OAuth proxy docs.

---

## Debugging & Cost Investigation

Set `LUNAR_DUMP_LLM_CALLS=1` to dump every LLM call to `logs/llm_calls/<utc-ts>_<id>_<caller>.json` — full request (messages, model, max_tokens) + response + timing + token counts. Useful for tracking down cache hit rates, runaway prompts, or reproducing prod calls offline.

`DEBUG=true` in `.env` enables verbose backend logging including the entire system prompt, history slice and response body for every action.

---

## Contributing

Contributions are welcome! This is an open-source project built for the community.

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Make your changes
4. Open a Pull Request

**Project Lunar is a scenario engine, not a game.** Avoid hardcoding world-specific logic (genre keywords, tier systems, named characters). All solutions should be scenario-agnostic — derive context from story cards, tone instructions, and lore that the user defined.

---

## Acknowledgments

- **[Inner-Self](https://github.com/LewdLeah/Inner-Self)** by LewdLeah — Inspiration for NPC inner thoughts and personality systems
- **AI Dungeon** — Pioneering AI-driven interactive fiction and story cards
- **Graphiti** — Temporal knowledge graph concepts
- **litellm** — Multi-provider LLM abstraction
- **[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)** — Subscription proxy for Anthropic and OpenAI-compatible model access

---

## License

MIT

---

<p align="center">
  <sub>Every story is unique. Every choice matters.</sub>
</p>
