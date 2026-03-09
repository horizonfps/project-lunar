# Project Lunar — Design Document
**Date:** 2026-03-09
**Status:** Approved

---

## 1. Vision

Project Lunar is an open-source platform for creating AI-powered RPG narrative scenarios. Authors build worlds (lore, NPCs, locations, factions); players live dynamically generated adventures narrated by LLMs with persistent memory, a reactive world, and creativity-based combat. It is not a game — it is a storytelling engine. Users create their own scenarios, similar to AI Dungeon but with a living world.

---

## 2. Target Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + Zustand + Tailwind CSS |
| Backend | Python 3.11+ + FastAPI + SSE streaming |
| LLM Abstraction | `litellm` (multi-provider) |
| Structured Output | `instructor` + Pydantic models |
| Event Store | SQLite (`events.db`) |
| World Graph | Neo4j via Graphiti (`world.db` logical) |
| Scenario Store | SQLite (`scenarios.db`) |
| Infrastructure | Docker Compose (Neo4j) + `install.bat` |

### LLM Providers Supported
- DeepSeek
- OpenAI (GPT-4o / GPT-4.1)
- Anthropic Claude

### Local-first Philosophy
Everything runs locally. No cloud deployment required. Docker Compose handles Neo4j. A single `install.bat` automates full setup for Windows users.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────┐
│              FRONTEND (React/Vite)           │
│  ScenarioBuilder │ GameCanvas │ Journal      │
│  WorldGraph View │ Settings   │ CombatFeed   │
└──────────────────────┬──────────────────────┘
                       │ REST + SSE
┌──────────────────────▼──────────────────────┐
│              BACKEND (FastAPI)               │
│                                             │
│  NarratorEngine  ◄──►  CombatEngine         │
│       │                     │               │
│  WorldReactor   ◄──►  EventStore            │
│       │                     │               │
│  MemoryEngine   ◄──►  GraphEngine           │
│       │                     │               │
│  PlotGenerator  ◄──►  JournalEngine         │
│       │                     │               │
│  ScenarioService             │              │
│       │                     │              │
│  LLMRouter (litellm)    SQLite x2 + Neo4j  │
└─────────────────────────────────────────────┘
              │
    ┌─────────┴──────────────────┐
    │ DeepSeek │ OpenAI │ Claude │
    └────────────────────────────┘
```

### Storage Strategy
- **`events.db` (SQLite)** — Immutable append-only event log. Every action (player, world tick, combat, NPC thought) stored as an event with `narrative_time`, `location`, `entities_involved`, and `payload`.
- **`scenarios.db` (SQLite)** — Scenarios authored by users (world config, story cards, AI instructions, saved campaigns).
- **Neo4j (Docker)** — World knowledge graph via Graphiti. Nodes: NPCs, Locations, Factions, Items. Edges: relationships with temporal metadata (when formed, current strength, history).

---

## 4. Modules

### 4.1 EventStore
- Append-only log of all events (immutable)
- Event types: `PLAYER_ACTION`, `NARRATOR_RESPONSE`, `WORLD_TICK`, `COMBAT_ACTION`, `COMBAT_RESULT`, `NPC_THOUGHT`, `JOURNAL_ENTRY`, `MEMORY_CRYSTAL`, `TIMESKIP`
- Periodic snapshots for fast world state reconstruction
- World state = event replay + cached snapshot

### 4.2 NarratorEngine
- Detects narrative mode: `NARRATIVE | COMBAT | META`
- Streams response via SSE (Server-Sent Events)
- Builds context from: MemoryEngine crystals + GraphEngine relevant entities + recent raw events
- Configurable per-scenario: temperature, max output tokens

### 4.3 CombatEngine
**Triggered when NarratorEngine detects combat mode.**

Rules:
- Player always acts first (except ambush/surprise — detected from narrative context)
- No HP/mana/levels — difficulty is purely narrative (derived from NPC power in GraphEngine)
- Action evaluation pipeline:
  1. **Anti-griefing check**: semantic coherence + physical feasibility (not text length)
  2. **Creativity score**: detail, originality, contextual appropriateness
  3. **Narrative difficulty**: NPC strength from world graph
  4. **Outcome roll**: `CRIT_FAIL | FAIL | SUCCESS | CRIT_SUCCESS`
- `CRIT_SUCCESS` → player gets +1 free action (NPC cannot react)
- `CRIT_FAIL` → NPC gets +2 actions (player cannot react)
- Anti-griefing: long incoherent actions are penalized; quality evaluated semantically

### 4.4 WorldReactor
- Subscribes to EventStore
- Each event carries a `narrative_time_delta` (seconds, hours, days, months in story time)
- **Light tick** (small delta): minor NPC state updates, relationship shifts
- **Heavy tick** (travel, timeskip): faction movements, political changes, NPC life events, location changes
- Off-screen world advances proportionally to narrative time elapsed

### 4.5 GraphEngine (Graphiti + Neo4j)
- Nodes: NPCs, Locations, Factions, Items, Events
- Edges: relationships with temporal weight (when formed, strength over time, last interaction)
- Queries: "Who does this NPC know?", "What happened in this location?", "Which factions are at war?"
- Populated from: Scenario lore extraction (Fabula-inspired) + live gameplay events

### 4.6 MemoryEngine — Crystal Memory
Three-tier memory system:

```
Raw Events        (last 20 actions)       → full token, immediate context
Short Crystals    (last 5 sessions)       → semantically compressed summaries
Long Crystals     (everything before)     → permanent extracted facts
World Graph       (Graphiti/Neo4j)        → entity relationships + temporal history
```

Facts never forgotten: "player betrayed the king in chapter 3" → Long Crystal + GraphEngine edge.

### 4.7 PlotGenerator
- Random event generator (context-aware, uses world state)
- Plot arc generator (main quest, side quests, faction arcs)
- NPC generator (procedural personality, backstory, goals, secrets)
- All generation respects existing world graph for coherence

### 4.8 JournalEngine
- Auto-detects relevant events from narrative (no manual logging)
- Categories: `DISCOVERY`, `RELATIONSHIP_CHANGE`, `COMBAT`, `DECISION`, `WORLD_EVENT`
- Player can view journal sorted by category or chronologically
- Journal entries also feed Long Crystal memory

### 4.9 LLMRouter
- Abstraction via `litellm`
- Per-scenario configurable: provider, model, temperature, max_tokens
- Fallback chain: primary → secondary → tertiary provider
- Structured output via `instructor` + Pydantic

### 4.10 ScenarioService
- Authors create scenarios via hybrid interface:
  - **Guided form**: world name, tone/style instructions, story cards (NPCs, locations, factions), opening narrative
  - **Lore field**: free-form world bible text → AI extracts entities and populates graph automatically (Fabula-inspired extraction)
- Multiple campaigns per scenario
- Export/import scenarios as JSON (shareable on GitHub, etc.)

---

## 5. Scenario Creator — Hybrid Interface

### Guided Form
- World name + genre
- Tone/style instructions for the AI narrator
- Story Cards: NPCs (name, personality, secrets, relationships), Locations (description, connected locations), Factions (goals, power level)
- Opening narrative
- AI narrator language

### Lore Field (Free-form)
- Author writes rich world bible in natural language
- AI extracts: entities, relationships, historical events, power dynamics
- Extracted data auto-populates the Graphiti world graph
- Author can review/edit extracted graph before starting campaign

---

## 6. Combat System — Detail

### Detection
NarratorEngine monitors narrative for combat triggers. When detected, switches to `COMBAT` mode and hands off to CombatEngine.

### Turn Order
- Player acts first
- Exception: NPC ambush/surprise (NarratorEngine signals `AMBUSH=true` to CombatEngine)

### Action Evaluation (Anti-Griefing)
```
action_text → LLM evaluator (structured output)
  ├── coherence_score: 0-10 (physical/logical feasibility)
  ├── creativity_score: 0-10 (originality, detail, tactical thinking)
  ├── context_score: 0-10 (appropriate to situation)
  └── final_quality = weighted_avg(coherence*0.4, creativity*0.4, context*0.2)

narrative_difficulty = GraphEngine.get_npc_power(npc_id) vs player_context

outcome_probability = f(final_quality, narrative_difficulty)
roll → CRIT_FAIL (<5%) | FAIL (5-40%) | SUCCESS (40-90%) | CRIT_SUCCESS (>90%)
```

### Anti-Griefing Rules
- Text length has zero weight in evaluation
- Incoherent long actions (e.g., physically impossible combos) → coherence penalty
- Repetitive actions from same player (same action twice) → novelty penalty
- Meta-gaming attempts ("I win the fight because I said so") → detected + rejected

---

## 7. World Reactivity

### Narrative Time Tracking
Every event records `narrative_time_delta`. WorldReactor accumulates total narrative time per campaign.

### Tick Thresholds
| Time Elapsed (narrative) | Tick Type | World Changes |
|---|---|---|
| < 1 hour | Micro | NPC mood shift |
| 1 hour – 1 day | Minor | NPC movements, minor news |
| 1 day – 1 week | Moderate | Faction decisions, rumors |
| 1 week – 1 month | Major | Political shifts, NPC life events |
| > 1 month | Heavy | Wars, deaths, new alliances, location changes |

### Timeskip
Player can request timeskip. NarratorEngine calculates elapsed time, WorldReactor runs proportional simulation, world state updates in graph, summary presented to player.

---

## 8. Frontend Views

| View | Description |
|---|---|
| **Home** | Scenario library + create new scenario |
| **ScenarioBuilder** | Hybrid form + lore field + graph preview |
| **GameCanvas** | Main play area — narrative feed + action input + combat overlay |
| **WorldMap** | Visual graph of NPCs/locations/factions (D3.js or similar) |
| **Journal** | Player diary with category filters |
| **Settings** | LLM provider config, API keys, temperature, output length |
| **NPC Inspector** | View NPC minds, relationship history (debug/author mode) |

---

## 9. Infrastructure

### docker-compose.yml
```yaml
services:
  neo4j:
    image: neo4j:5
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/lunar_password
    volumes:
      - neo4j_data:/data
```

### install.bat
1. Check Docker Desktop installed
2. `docker-compose up -d` (start Neo4j)
3. Create Python venv + `pip install -r requirements.txt`
4. `npm install` in frontend
5. Start backend (`uvicorn`) + frontend (`vite dev`) in separate terminals
6. Open browser to `localhost:3000`

---

## 10. Key References Used

| Reference | Applied In |
|---|---|
| Graphiti (getzep) | GraphEngine — temporal world knowledge graph |
| Inner Self (LewdLeah) | NPC Minds — private thoughts, hidden goals |
| Letta / Mem0 | MemoryEngine — crystal memory architecture |
| Outlines / instructor | LLMRouter — structured output from LLMs |
| TinyTroupe | PlotGenerator — NPC persona simulation |
| Fabula | ScenarioService — lore extraction to graph |
| STORYTELLER paper | NarratorEngine — SVO plot planning for coherence |
| Drama Llama paper | CombatEngine — storylet + LLM hybrid triggers |
| Context Weaver | PlotGenerator — procedural event library |
| StoryBench paper | Testing — long-term memory evaluation methodology |

---

## 11. Out of Scope (v1)

- Cloud deployment
- Multiplayer
- Image / audio generation
- Mobile app
- User authentication / accounts (local-only)
