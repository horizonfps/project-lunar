<p align="center">
  <img src="docs/banner.png" alt="Project Lunar" width="100%" />
</p>

<p align="center">
  <strong>An open-source storytelling engine where every choice reshapes the world.</strong><br>
  <sub>Authors create worlds. Players live adventures. AI narrates everything.</sub>
</p>

<p align="center">
  <a href="#features">Features</a> &middot;
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#memory-system">Memory</a> &middot;
  <a href="#combat-system">Combat</a> &middot;
  <a href="#llm-providers">LLM Providers</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

---

## What is Project Lunar?

Project Lunar is a **local-first** narrative RPG platform powered by AI. Authors build scenarios with lore, NPCs, locations, and factions. Players live through dynamically generated adventures narrated by LLMs with persistent memory, a reactive world, and creativity-based combat.

No HP bars. No mana pools. No grinding. Just **storytelling**.

---

## Features

| | Feature | Description |
|---|---------|-------------|
| **Narrator** | Mode-Aware Engine | Switches between Narrative, Combat, and Meta modes with real-time SSE streaming |
| **Memory** | 3-Tier Crystal Memory | Raw events → short crystals → long crystals with structured crystallization (relationships, promises, key events) |
| **World** | Reactive World | Off-screen world evolves proportionally to narrative time elapsed |
| **Combat** | Creativity-Based | No stats — actions scored on coherence, creativity, and context with anti-griefing |
| **NPCs** | Independent Minds | Each NPC maintains private thoughts (feeling, goal, opinion, secret plan) updated every turn |
| **Graph** | Knowledge Graph | Neo4j-powered entity tracking with relationship extraction and canonical name resolution |
| **Journal** | Auto-Detection | AI identifies significant events (discoveries, relationship changes, combat, decisions) and logs them |
| **Plots** | Auto-Plot Generator | Macro story arcs, micro-hooks, and NPC generation on dynamic cooldowns with plot lock system |
| **Inventory** | Item Lifecycle | Narrative-driven item tracking via inline tags (`[ITEM_ADD]`, `[ITEM_USE]`, `[ITEM_LOSE]`) |
| **Scenarios** | Builder + Import/Export | Create and share worlds as JSON with AI-powered lore extraction |
| **Rewind** | Undo System | Rewind last action to explore different story branches |
| **Multi-LLM** | Provider Switching | DeepSeek, Anthropic (Sonnet/Opus), and OpenAI — switch at runtime via settings |

---

## Quickstart

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **Docker** (for Neo4j)
- An LLM API key: **DeepSeek** ([get one](https://platform.deepseek.com/)), **Anthropic**, or **OpenAI**

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

# Start Neo4j
docker-compose up -d neo4j

# Backend
cd backend
source venv/bin/activate   # venv\Scripts\activate on Windows
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm run dev
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
```

You can switch between providers at runtime in the Settings panel — no restart needed.

---

## How to Play

1. **Create a Scenario** — Fill in world details, paste free-form lore (AI extracts entities automatically), set the tone
2. **Play** — Select a scenario, create a campaign, and dive in
3. **Act** — Use the action selector:
   - **DO** — Perform a physical action
   - **SAY** — Speak in character
   - **CONTINUE** — Let the story flow
   - **META** — Ask the narrator out-of-character questions about the world state
4. **Explore** — Open panels for inventory, world map, NPC minds, journal, memory crystals, and plot generation

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│  GameCanvas · ActionInput · Settings · WorldMap · NPC Minds     │
│  Journal · Inventory · MemoryInspector · PlotGenerator          │
└────────────────────────────┬────────────────────────────────────┘
                             │ SSE / REST
┌────────────────────────────▼────────────────────────────────────┐
│                     FastAPI Backend                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   GameSession (orchestrator)             │   │
│  │  process_action() → detect_mode → narrate → side effects │   │
│  └────┬─────┬──────┬──────┬──────┬──────┬──────┬──────┬─────┘   │
│       │     │      │      │      │      │      │      │         │
│  Narrator Memory Combat  NPC   Journal Graph  World  Plot       │
│  Engine  Engine Engine  Minds  Engine  Engine Reactor Generator │
│       │     │      │      │      │      │      │      │         │
│  ┌────▼─────▼──────▼──────▼──────▼──────┤      │      │         │
│  │          LLM Router (litellm)        │      │      │         │
│  │  DeepSeek · Anthropic · OpenAI       │      │      │         │
│  └──────────────────────────────────────┘      │      │         │
│  ┌──────────────────┐  ┌──────────────────┐    │      │         │
│  │ EventStore (SQL) │  │ ScenarioStore    │    │      │         │
│  │ Append-only log  │  │ Worlds/Campaigns │    │      │         │
│  └──────────────────┘  └──────────────────┘    │      │         │
└────────────────────────────────────────────────┼──────┘─────────┘
                                                 │
                                    ┌────────────▼──────────┐
                                    │   Neo4j (Docker)      │
                                    │   Knowledge Graph     │
                                    └───────────────────────┘
```

### Engine Breakdown

| Engine | Purpose | Key Behavior |
|--------|---------|-------------|
| **NarratorEngine** | Mode detection, prompt building, streaming | Builds multi-section system prompts with context budgeting; single-call mode for Anthropic |
| **MemoryEngine** | 3-tier memory compression | Auto-crystallizes every 4 actions; structured format (RELATIONSHIPS, PROMISES, KEY_EVENTS, PLAYER_STATE, WORLD_STATE) |
| **CombatEngine** | Creativity-scored combat | Scores coherence/creativity/context (40/40/20 weight); anti-griefing rejects meta-gaming |
| **NpcMindEngine** | NPC inner thoughts | Tracks feeling, goal, opinion_of_player, secret_plan per NPC; fuzzy name dedup with LLM confirmation |
| **JournalEngine** | Auto-event detection | Categories: DISCOVERY, RELATIONSHIP_CHANGE, COMBAT, DECISION, WORLD_EVENT |
| **GraphEngine** | Neo4j entity graph | Node types: NPC, LOCATION, FACTION, ITEM, EVENT; canonical name resolution for short→full names |
| **WorldReactor** | Off-screen world changes | Tick types scaled by time: MICRO (<1h, no change) → HEAVY (>1 month, wars/deaths) |
| **PlotGenerator** | Auto-generated story elements | Macro arcs (foreshadowing), micro-hooks (scene details), NPC generation with cooldown timers |
| **InventoryEngine** | Item lifecycle tracking | States: carried/used/lost; narrative-driven via inline tags parsed from LLM output |
| **LLMRouter** | Multi-provider abstraction | litellm wrapper with primary/fallback, streaming + completion, max_tokens override |

---

## Memory System

Project Lunar uses a 3-tier memory architecture so the AI never forgets, even in long sessions:

```
Action 1─4: [raw events in context]
                ↓ auto-crystallize (every 4 actions)
Action 5─8: [crystal of 1-4] + [raw events 5-8]
                ↓
Action 9+:  [crystal of 1-8] + [raw events 9-12]
                ↓
Action 50:  [long crystal: actions 1-35] + [short crystal: 36-45] + [raw: 46-50]
```

**What the LLM sees at action 50:**
- Crystallized summary of actions 1-35 (compressed to structured format)
- Recent crystal of actions 36-45
- Last 10 raw events (uncompressed)
- Last 30 conversation messages (full text)
- Current NPC states (thoughts of all active NPCs)
- Last 8 journal entries
- Neo4j graph relationships

**Crystallization format:**
```
RELATIONSHIPS: [who met who and what they discussed]
PROMISES: [agreements, pacts, deals]
KEY_EVENTS: [major plot points in chronological order]
PLAYER_STATE: [emotional state, goals, grudges]
WORLD_STATE: [faction standings, location changes, threats]
```

---

## Combat System

Project Lunar uses a **creativity-based combat system** — no HP, mana, or levels.

Every action is evaluated on three axes:

| Axis | Weight | Description |
|------|--------|-------------|
| **Coherence** | 40% | Does the action make physical/logical sense? |
| **Creativity** | 40% | Is it original and unexpected? |
| **Context** | 20% | Does it use the environment and narrative? |

| Outcome | Probability | Effect |
|---------|------------|--------|
| Critical Success | High quality + luck | Spectacular success + 1 free action |
| Success | quality × 0.65 + (1-difficulty) × 0.35 | Action succeeds as intended |
| Fail | Below threshold | Action fails, story continues |
| Critical Fail | Low quality + bad luck | Action backfires — NPC gains +2 actions |

Anti-griefing rejects meta-gaming ("I kill everyone instantly") and physically impossible actions.

---

## LLM Providers

Project Lunar supports multiple LLM providers via [litellm](https://github.com/BerriAI/litellm). Switch providers at runtime in the Settings panel.

| Provider | Models | Context | Pipeline | Cost |
|----------|--------|---------|----------|------|
| **DeepSeek** | deepseek-chat, deepseek-reasoner | 200K | Streaming + multi-call (5-6 LLM calls/action) | ~$0.002/action |
| **Anthropic** | claude-sonnet-4-6, claude-opus-4-6 | 1M | Single-call + prompt caching (1 LLM call/action) | ~$0.07/action |
| **OpenAI** | gpt-4o, gpt-4o-mini | 128K | Streaming + multi-call | ~$0.01/action |

### Provider Quality Comparison

After extensive playtesting (35+ actions per provider across multiple scenarios), here's how each provider performs as a storytelling engine:

#### DeepSeek — Best Value 🏆

**Narrative style:** Light novel — vivid, emotional, cinematic.

DeepSeek delivers surprisingly rich storytelling at a fraction of the cost. Characters have well-defined emotions, combat scenes are dynamic and creative, and the AI consistently respects scenario rules and player technique limitations. It introduces original plot elements (items, locations, backstory reveals) that feel earned rather than random. At ~$0.002/action, it's absurdly cost-effective — you can play hundreds of actions for pennies.

**Strengths:** Creative NPC dialogue, emotionally resonant moments, excellent technique/power consistency, emergent narrative details (e.g., inventing meaningful items tied to backstory).

**Weaknesses:** Occasionally verbose. Slightly less character depth compared to Anthropic. Takes some creative liberties with player dialogue.

#### Anthropic (Claude) — Best Quality 👑

**Narrative style:** Literary fiction — a true novelist narrating your adventure.

Any Claude model (even Sonnet) produces writing that is genuinely beautiful. Characters have significantly deeper psychological profiles — their motivations feel layered, their dialogue has subtext, and emotional beats hit harder. The AI builds tension masterfully and makes every choice feel consequential. Sonnet specifically offers the best speed-to-quality ratio in the market.

**Strengths:** Deepest character work, most emotionally impactful writing, best instruction adherence, nuanced moral dilemmas, subtlety in foreshadowing.

**Weaknesses:** Expensive (~$0.07/action). Even with single-call mode and prompt caching, long sessions add up fast.

#### OpenAI (GPT) — Not Recommended ⚠️

**Narrative style:** Technical manual pretending to be a novel.

OpenAI models produce text that *looks* good at first glance but breaks down over extended play. Characters feel mechanized — they say the right words but lack literary depth. The AI tends to fall into repetitive narrative patterns (same sentence structures, same dramatic beats) and progressively ignores narrator instructions, defaulting to its own generic storytelling style. Still more expensive than DeepSeek with significantly worse results.

**Strengths:** Fast response times. Adequate for short sessions or testing.

**Weaknesses:** Repetitive narrative style, poor long-term instruction adherence, characters lack personality depth, formulaic combat descriptions, higher cost than DeepSeek for lower quality.

#### TL;DR

| | DeepSeek | Anthropic | OpenAI |
|---|---------|-----------|--------|
| **Quality** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **Cost/action** | ~$0.002 | ~$0.07 | ~$0.01 |
| **Character depth** | Good | Exceptional | Shallow |
| **Instruction adherence** | Good | Excellent | Poor over time |
| **Recommended for** | Daily play, long campaigns | Special moments, premium experience | Testing only |

### Anthropic Single-Call Mode

When using Anthropic, the engine consolidates 5-6 separate LLM calls into **one** API call that returns:
- Narrative text (full prose)
- Mode classification (NARRATIVE/COMBAT/META)
- NPC thought updates
- Entity/relationship extraction
- World changes

The static portion of the system prompt (role + tone + narrator rules + JSON format) is marked with `cache_control` for Anthropic's prompt caching, reducing input token costs by ~90% on repeated actions within the same scenario.

### DeepSeek Streaming Mode

DeepSeek uses the traditional pipeline with real-time streaming:
1. `detect_mode()` — classify action
2. `stream_narrative()` — stream narrative to frontend via SSE
3. `update_npc_thoughts()` — extract NPC mental states
4. `extract_entities_to_graph()` — populate Neo4j
5. `process_tick()` — world evolution
6. `auto_crystallize()` — memory compression (every 4 turns)

---

## Auto-Plot System

The engine automatically generates story elements on dynamic cooldowns:

| Type | Min Turns | Min Time | Cooldown | Max per Campaign |
|------|-----------|----------|----------|-----------------|
| **Micro-Hook** | 3 | 15 min | 4 turns | 12 |
| **NPC Generation** | 5 | 30 min | 6 turns | 8 |
| **Plot Arc** | 8 | 2 hours | 9 turns | 6 |

- **Micro-hooks**: Scene details woven into the next narration (mysterious object, NPC behaving oddly)
- **NPC Generation**: New characters with name, personality, power level, secret, goal, appearance
- **Plot Arcs**: High-level story seeds for the narrator to foreshadow subtly

A **plot lock** ensures only one active element at a time — new elements wait until the current one is consumed (after 4+ turns of development).

---

## Project Structure

```
project-lunar/
├── backend/
│   └── app/
│       ├── api/               # FastAPI routes
│       │   ├── routes_game.py     # Game actions, SSE streaming, state queries
│       │   └── routes_scenarios.py # Scenario CRUD, import/export
│       ├── db/                # Persistence
│       │   ├── event_store.py     # Append-only event log (SQLite)
│       │   └── scenario_store.py  # Scenarios, campaigns, story cards
│       ├── engines/           # Core systems
│       │   ├── narrator_engine.py     # Mode detection, prompts, streaming, single-call
│       │   ├── memory_engine.py       # 3-tier crystallization
│       │   ├── combat_engine.py       # Creativity-based combat + anti-griefing
│       │   ├── npc_mind_engine.py     # NPC thoughts + fuzzy dedup
│       │   ├── journal_engine.py      # Auto-event detection
│       │   ├── graph_engine.py        # Neo4j knowledge graph
│       │   ├── world_reactor.py       # Off-screen world evolution
│       │   ├── plot_generator.py      # Auto-plot (arcs, hooks, NPCs)
│       │   ├── inventory_engine.py    # Item lifecycle
│       │   ├── llm_router.py          # Multi-provider LLM abstraction
│       │   └── graphiti_engine.py     # Temporal knowledge graph
│       ├── services/
│       │   ├── game_session.py        # Main orchestrator (1000+ lines)
│       │   └── scenario_service.py    # Scenario management
│       ├── utils/
│       │   └── json_parsing.py        # Robust JSON extraction from LLM output
│       ├── config.py              # Pydantic settings + .env
│       └── main.py                # FastAPI entry point
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── GameCanvas.jsx         # Main gameplay UI + SSE handler
│       │   ├── ActionInput.jsx        # DO/SAY/CONTINUE/META input
│       │   ├── CombatOverlay.jsx      # Combat mode UI
│       │   ├── SettingsPanel.jsx      # LLM provider/model/temperature config
│       │   ├── InventoryPanel.jsx     # Item display
│       │   ├── JournalPanel.jsx       # Event log by category
│       │   ├── WorldMapModal.jsx      # Force-graph Neo4j visualization
│       │   ├── MemoryInspector.jsx    # Crystal viewer
│       │   ├── NpcInspector.jsx       # NPC thought browser
│       │   ├── PlotGeneratorPanel.jsx # On-demand generation
│       │   ├── TimeskipModal.jsx      # Time advancement
│       │   └── ScenarioBuilder.jsx    # World creation with lore extraction
│       ├── store.js               # Zustand state management
│       ├── api.js                 # REST + SSE API helpers
│       └── App.jsx                # Routes (/, /create, /play)
├── docker-compose.yml         # Neo4j container
├── .env.example               # Environment template
└── install.sh                 # One-command setup
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 · Vite · Zustand · Tailwind CSS · Framer Motion |
| Backend | Python 3.10+ · FastAPI · SQLite (event sourcing) |
| Knowledge Graph | Neo4j (Docker) · Graphiti-core (temporal) |
| LLM | litellm (DeepSeek · Anthropic · OpenAI) |
| Visualization | react-force-graph-2d · React Markdown · Lucide icons |

---

## Running Tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -v --cov=app --cov-report=term-missing
```

143 tests covering all engines, services, and API routes.

---

## API Reference

### Game Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/game/action` | Stream game action (SSE) |
| POST | `/api/game/rewind` | Undo last action |
| POST | `/api/game/timeskip` | Advance narrative time |
| GET | `/api/game/{id}/state` | Current session state |
| GET | `/api/game/{id}/memory` | Memory crystals |
| GET | `/api/game/{id}/journal` | Journal entries |
| GET | `/api/game/{id}/inventory` | Player inventory |
| GET | `/api/game/{id}/npc-minds` | All NPC states |
| GET | `/api/game/{id}/world-graph` | Neo4j graph data |
| POST | `/api/game/generate` | Generate NPC/event/plot |
| POST | `/api/game/search` | Search knowledge graph |

### Scenario Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scenarios` | List all scenarios |
| POST | `/api/scenarios` | Create scenario |
| POST | `/api/scenarios/import` | Import from JSON |
| POST | `/api/scenarios/{id}/export` | Export as JSON |
| POST | `/api/scenarios/{id}/campaigns` | Create campaign |
| DELETE | `/api/scenarios/{id}` | Delete scenario |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings` | Current LLM config |
| POST | `/api/settings` | Update provider/model/temperature/max_tokens |

---

## Contributing

Contributions are welcome! This is an open-source project built for the community.

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Write tests for your changes
4. Run `pytest tests/ -v` to verify
5. Open a Pull Request

---

## Acknowledgments

- **[Inner-Self](https://github.com/LewdLeah/Inner-Self)** by LewdLeah — Inspiration for NPC inner thoughts and personality systems
- **AI Dungeon** — Pioneering AI-driven interactive fiction and story cards
- **Graphiti** — Temporal knowledge graph concepts
- **litellm** — Multi-provider LLM abstraction

---

## License

MIT

---

<p align="center">
  <sub>Every story is unique. Every choice matters.</sub>
</p>
