# Project Lunar — Agent Implementation Checklist

> This file tracks TDD implementation progress phase by phase.
> Full implementation plan: `docs/plans/2026-03-09-project-lunar-implementation.md`
> Design document: `docs/plans/2026-03-09-project-lunar-design.md`

---

## Phase 0 — Infrastructure & Project Scaffold

### Task 0.1: Project Directory Structure
- [x] Create backend/app directory tree with sub-packages
- [x] Create `docker-compose.yml` with Neo4j service and health check
- [x] Create `.env.example` with all required keys (OpenAI, Anthropic, DeepSeek, Neo4j)
- [x] Create `.gitignore` (venv, node_modules, .env, *.db)
- [x] Create `install.bat` (Docker check → Neo4j up → venv → pip → npm → open browser)
- [x] Commit: `chore: initial project scaffold with docker and install script`

### Task 0.2: Backend Dependencies
- [x] Create `backend/requirements.txt` (fastapi, uvicorn, litellm, instructor, graphiti-core, neo4j, etc.)
- [x] Create `backend/requirements-dev.txt` (pytest, pytest-asyncio, pytest-cov, httpx)
- [x] Create `backend/app/config.py` with `pydantic-settings` Settings class
- [x] Install and verify: `python -c "import fastapi, litellm, graphiti_core; print('OK')"`
- [x] Commit: `chore: add backend dependencies and config`

### Task 0.3: Frontend Scaffold
- [x] Scaffold with `npm create vite@latest . -- --template react`
- [x] Install dependencies: zustand, axios, react-router-dom, lucide-react, react-markdown, framer-motion
- [x] Install dev dependencies: tailwindcss, postcss, autoprefixer
- [x] Configure `tailwind.config.js` and `src/index.css`
- [x] Verify dev server starts on http://localhost:5173
- [x] Commit: `chore: scaffold React/Vite frontend with Tailwind`

---

## Phase 1 — Data Layer

### Task 1.1: EventStore
- [x] Write failing tests: `backend/tests/db/test_event_store.py`
  - [x] `test_append_event`
  - [x] `test_get_recent_events`
  - [x] `test_get_total_narrative_time`
  - [x] `test_events_are_immutable`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/db/event_store.py`
  - [x] `EventType` enum (9 types)
  - [x] `Event` frozen dataclass
  - [x] `EventStore` class with SQLite backend
  - [x] `append()` method
  - [x] `get_recent()` method
  - [x] `get_total_narrative_time()` method
- [x] Run tests → verify 4 PASS
- [x] Commit: `feat: add immutable EventStore with SQLite`

### Task 1.2: ScenarioStore
- [x] Write failing tests: `backend/tests/db/test_scenario_store.py`
  - [x] `test_create_and_get_scenario`
  - [x] `test_add_story_card`
  - [x] `test_create_campaign`
  - [x] `test_list_scenarios`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/db/scenario_store.py`
  - [x] `StoryCardType` enum (NPC, LOCATION, FACTION, ITEM, LORE)
  - [x] `Scenario`, `StoryCard`, `Campaign` dataclasses
  - [x] `ScenarioStore` class with 3 SQLite tables
  - [x] CRUD methods for all 3 entities
- [x] Run tests → verify 4 PASS
- [x] Commit: `feat: add ScenarioStore with scenarios, campaigns, and story cards`

### Task 1.3: GraphEngine (Graphiti + Neo4j)
- [x] Verify Neo4j is running: `docker-compose up -d neo4j`
- [x] Write failing tests: `backend/tests/engines/test_graph_engine.py`
  - [x] `test_add_npc_node`
  - [x] `test_add_relationship`
  - [x] `test_get_npc_power_level`
  - [x] `test_query_neighbors`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/graph_engine.py`
  - [x] `WorldNodeType` enum
  - [x] `WorldNode`, `Relationship` dataclasses
  - [x] `GraphEngine` async class with Neo4j driver
  - [x] `initialize()` — create constraints
  - [x] `add_node()` method
  - [x] `add_relationship()` method
  - [x] `get_npc_power()` method
  - [x] `get_neighbors()` method
  - [x] `clear_campaign()` method (for test cleanup)
- [x] Run tests → verify 4 PASS
- [x] Commit: `feat: add GraphEngine with Neo4j world graph and temporal relationships`

---

## Phase 2 — LLM Layer

### Task 2.1: LLMRouter
- [x] Write failing tests: `backend/tests/engines/test_llm_router.py`
  - [x] `test_router_builds_model_string` (DeepSeek)
  - [x] `test_router_builds_openai_model`
  - [x] `test_router_builds_anthropic_model`
  - [x] `test_complete_returns_text`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/llm_router.py`
  - [x] `LLMProvider` enum (OPENAI, ANTHROPIC, DEEPSEEK)
  - [x] `LLMConfig` dataclass
  - [x] `LLMRouter` class
  - [x] `_build_model_string()` method
  - [x] `complete()` async method with fallback chain
  - [x] `stream()` async generator
- [x] Run tests → verify 4 PASS
- [x] Commit: `feat: add LLMRouter with multi-provider support and fallback chain`

---

## Phase 3 — Memory & World Reactor

### Task 3.1: MemoryEngine (Crystal Memory)
- [x] Write failing tests: `backend/tests/engines/test_memory_engine.py`
  - [x] `test_raw_context_returns_recent_events`
  - [x] `test_crystallize_creates_short_crystal`
  - [x] `test_build_context_window`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/memory_engine.py`
  - [x] `CrystalTier` enum (SHORT, LONG)
  - [x] `MemoryCrystal` dataclass
  - [x] `MemoryEngine` class
  - [x] `get_raw_context()` method
  - [x] `crystallize()` async method (LLM compression)
  - [x] `build_context_window()` method (3-tier assembly)
- [x] Run tests → verify 3 PASS
- [x] Commit: `feat: add MemoryEngine with 3-tier crystal memory system`

### Task 3.2: WorldReactor
- [x] Write failing tests: `backend/tests/engines/test_world_reactor.py`
  - [x] `test_classify_tick_micro`
  - [x] `test_classify_tick_minor`
  - [x] `test_classify_tick_major`
  - [x] `test_classify_tick_heavy`
  - [x] `test_process_tick_returns_world_changes`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/world_reactor.py`
  - [x] `TickType` enum (MICRO, MINOR, MODERATE, MAJOR, HEAVY)
  - [x] `TICK_THRESHOLDS` and `TICK_PROMPTS` constants
  - [x] `WorldReactor` class
  - [x] `classify_tick()` method
  - [x] `process_tick()` async method (LLM world simulation)
- [x] Run tests → verify 5 PASS
- [x] Commit: `feat: add WorldReactor with narrative time tick classification`

---

## Phase 4 — Narrative & Combat

### Task 4.1: CombatEngine
- [x] Write failing tests: `backend/tests/engines/test_combat_engine.py`
  - [x] `test_evaluate_creative_action_high_score`
  - [x] `test_evaluate_simple_action_low_score`
  - [x] `test_anti_griefing_rejects_meta_action`
  - [x] `test_roll_outcome_high_quality_high_chance`
  - [x] `test_roll_outcome_low_quality_hard_npc`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/combat_engine.py`
  - [x] `CombatOutcome` enum (CRIT_FAIL, FAIL, SUCCESS, CRIT_SUCCESS)
  - [x] `ActionEvaluation` dataclass
  - [x] `AntiGriefingResult` dataclass
  - [x] `CombatEngine` class
  - [x] `anti_griefing_check()` async method (meta-game detection)
  - [x] `evaluate_action()` async method (coherence × creativity × context)
  - [x] `roll_outcome()` method (probability → outcome)
- [x] Run tests → verify 5 PASS
- [x] Commit: `feat: add CombatEngine with creativity evaluation and anti-griefing`

### Task 4.2: NarratorEngine
- [x] Write failing tests: `backend/tests/engines/test_narrator_engine.py`
  - [x] `test_detect_narrative_mode_combat`
  - [x] `test_detect_narrative_mode_narrative`
  - [x] `test_detect_meta_mode`
  - [x] `test_build_system_prompt`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/narrator_engine.py`
  - [x] `NarrativeMode` enum (NARRATIVE, COMBAT, META)
  - [x] `NarratorEngine` class
  - [x] `detect_mode()` async method (returns mode + narrative_time_seconds + ambush)
  - [x] `build_system_prompt()` method
  - [x] `stream_narrative()` async generator (SSE-ready)
- [x] Run tests → verify 4 PASS
- [x] Commit: `feat: add NarratorEngine with mode detection and SSE streaming`

---

## Phase 5 — Generation & Journal

### Task 5.1: PlotGenerator
- [x] Write failing tests: `backend/tests/engines/test_plot_generator.py`
  - [x] `test_generate_npc`
  - [x] `test_generate_random_event`
  - [x] `test_generate_plot_arc`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/plot_generator.py`
  - [x] `GeneratedNPC` dataclass
  - [x] `RandomEvent` dataclass
  - [x] `PlotGenerator` class
  - [x] `generate_npc()` async method
  - [x] `generate_random_event()` async method
  - [x] `generate_plot_arc()` async method
- [x] Run tests → verify 3 PASS
- [x] Commit: `feat: add PlotGenerator with NPC, event, and plot arc generation`

### Task 5.2: JournalEngine
- [x] Write failing tests: `backend/tests/engines/test_journal_engine.py`
  - [x] `test_evaluate_relevant_event`
  - [x] `test_skip_irrelevant_event`
  - [x] `test_get_journal`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/engines/journal_engine.py`
  - [x] `JournalCategory` enum (DISCOVERY, RELATIONSHIP_CHANGE, COMBAT, DECISION, WORLD_EVENT)
  - [x] `JournalEntry` dataclass
  - [x] `JournalEngine` class
  - [x] `evaluate_and_log()` async method (LLM-based relevance detection)
  - [x] `get_journal()` method
  - [x] `get_by_category()` method
- [x] Run tests → verify 3 PASS
- [x] Commit: `feat: add JournalEngine with auto-detection and categorization`

---

## Phase 6 — Scenario Service & Lore Extraction

### Task 6.1: ScenarioService + Lore Extraction
- [x] Write failing tests: `backend/tests/services/test_scenario_service.py`
  - [x] `test_extract_lore_creates_story_cards`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/services/scenario_service.py`
  - [x] `ScenarioService` class
  - [x] `extract_lore_to_cards()` async method (Fabula-inspired extraction)
- [x] Run tests → verify 1 PASS
- [x] Commit: `feat: add ScenarioService with lore extraction to story cards`

---

## Phase 7 — FastAPI Routes

### Task 7.1: Main App & Routes
- [x] Write failing tests: `backend/tests/api/test_routes_scenarios.py`
  - [x] `test_health`
  - [x] `test_create_scenario`
  - [x] `test_list_scenarios`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/main.py` (FastAPI app + CORS + router includes)
- [x] Implement `backend/app/api/routes_scenarios.py` (CRUD + story cards)
- [x] Implement `backend/app/api/routes_game.py` (placeholder action endpoint)
- [x] Run tests → verify 3 PASS
- [x] Commit: `feat: add FastAPI app with scenario and game routes`

---

## Phase 8 — Engine Wiring & SSE Game Loop

### Task 8.1: GameSession — Wire All Engines
- [x] Write failing tests: `backend/tests/services/test_game_session.py`
  - [x] `test_process_narrative_action`
- [x] Run tests → verify FAIL
- [x] Implement `backend/app/services/game_session.py`
  - [x] `GameSession` class
  - [x] `process_action()` async generator
  - [x] `_handle_narrative()` private method
  - [x] `_handle_combat()` private method
- [x] Update `routes_game.py` to wire `GameSession` into SSE `StreamingResponse`
- [x] Run tests → verify 1 PASS
- [x] Manual test: `curl -N -X POST http://localhost:8000/api/game/action -d '{"campaign_id":"test","action":"I open the door"}'`
- [x] Commit: `feat: wire all engines into GameSession with SSE streaming game loop`

---

## Phase 9 — Frontend

### Task 9.1: Frontend Store & API Client
- [x] Implement `frontend/src/store.js` (Zustand store)
  - [x] Scenario state (list, active, campaignId)
  - [x] Message state (append, streaming append)
  - [x] Journal state
  - [x] Settings state (provider, model, temperature, max_tokens)
- [x] Implement `frontend/src/api.js`
  - [x] `fetchScenarios()`
  - [x] `createScenario()`
  - [x] `addStoryCard()`
  - [x] `streamAction()` with SSE reader
- [x] Commit: `feat: add Zustand store and SSE API client`

### Task 9.2: GameCanvas Component
- [x] Implement `frontend/src/components/GameCanvas.jsx`
  - [x] Message list with auto-scroll
  - [x] User messages (right-aligned, indigo bubble)
  - [x] AI responses (prose, markdown rendered)
  - [x] Streaming indicator
- [x] Implement `frontend/src/components/ActionInput.jsx`
  - [x] Action type selector (DO / SAY / CONTINUE / META)
  - [x] Text input + submit button
  - [x] Disabled state during streaming
- [x] Commit: `feat: add GameCanvas with SSE streaming and action type selector`

### Task 9.3: ScenarioBuilder Component
- [x] Implement `frontend/src/components/ScenarioBuilder.jsx`
  - [x] Title, description, tone instructions, opening narrative fields
  - [x] Language selector (en / pt-br)
  - [x] Lore text area with AI extraction hint
  - [x] Submit creates scenario and redirects to home
- [x] Commit: `feat: add ScenarioBuilder with hybrid form and lore extraction field`

### Task 9.4: App Router & Home
- [x] Implement `frontend/src/App.jsx`
  - [x] Home route with scenario grid
  - [x] `/create` route → ScenarioBuilder
  - [x] `/play` route → GameCanvas
  - [x] "Play" button sets activeScenario + new campaignId
- [x] Update `frontend/src/main.jsx`
- [x] Commit: `feat: add app router with home, scenario builder, and game canvas`

---

## Phase 10 — Integration & Polish

### Task 10.1: Full Test Suite
- [x] Run `pytest tests/ -v --cov=app --cov-report=term-missing`
- [x] Verify coverage > 70% (achieved 93% with 78 tests passing)
- [x] Fix any failing tests (none failing)

### Task 10.2: Full Stack Smoke Test
- [x] Start: `docker-compose up -d neo4j`
- [x] Start: `uvicorn app.main:app --reload --port 8000`
- [x] Start: `npm run dev`
- [x] Create a scenario via UI (Playwright: "The Shattered Kingdoms")
- [x] Start a campaign and verify streaming works (SSE streaming confirmed)
- [x] Verify world tick fires on long action (WORLD_TICK with 259200s delta confirmed)
- [ ] Commit: `chore: verify full stack integration and smoke test`

### Task 10.3: README.md
- [x] Write `README.md` with installation, usage, and contribution guide
- [x] Document all features with brief descriptions
- [x] Add reference acknowledgments
- [ ] Commit: `docs: add README with installation and usage guide`

---

## Feature Backlog (Post-MVP)

- [x] **NPC Minds** — private key-value thoughts per NPC (inspired by Inner-Self) + NPC Inspector panel
- [x] **WorldMap View** — force-directed graph visualization of world entities (react-force-graph-2d)
- [x] **Journal View** — categorized player diary UI (sidebar with category filters + real-time SSE updates)
- [x] **Settings Panel** — LLM provider selector, temperature/token sliders (modal in GameCanvas)
- [x] **NPC Inspector** — author/debug mode to view NPC mind state (modal with expandable thought categories)
- [x] **Scenario Export/Import** — JSON format for sharing on GitHub
- [x] **Graphiti Full Integration** — hybrid approach: Graphiti temporal episodes alongside raw Neo4j graph + search endpoint
- [x] **Timeskip UI** — explicit timeskip command with world summary (preset time periods + world evolution)
- [x] **Combat Overlay** — visual indicator when in COMBAT mode (border glow + badge + narrator label change)
- [x] **Plot Generator UI** — button to generate random events or NPC suggestions (NPC/Event/Plot Arc tabs)
- [x] **Memory Crystal Inspector** — view current crystal chain + manual crystallize button

---

## Legend

| Symbol | Meaning |
|---|---|
| `- [ ]` | Not started |
| `- [x]` | Complete |
| `- [~]` | In progress |

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/your-username/project-lunar
install.bat

# 2. Add API keys
notepad .env

# 3. Start backend
cd backend && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000

# 4. Start frontend
cd frontend && npm run dev

# 5. Open http://localhost:5173
```
