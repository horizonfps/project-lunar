# Project Lunar — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an open-source AI RPG storytelling engine platform where authors create scenarios and players live dynamically generated adventures with persistent memory, a reactive world, and creativity-based combat — all running locally.

**Architecture:** Event-sourcing core (immutable SQLite event log) + Graphiti temporal knowledge graph (Neo4j via Docker) for world state. FastAPI backend with SSE streaming for real-time narrative. React/Vite frontend with Zustand state. Multi-provider LLM via litellm.

**Tech Stack:** Python 3.11+, FastAPI, litellm, instructor, Pydantic v2, Graphiti, Neo4j 5, SQLite, React 18, Vite, Zustand, Tailwind CSS, Docker Compose.

---

## Phase 0 — Infrastructure & Project Scaffold

### Task 0.1: Project Directory Structure

**Files:**
- Create: `backend/` (directory)
- Create: `frontend/` (directory)
- Create: `docker-compose.yml`
- Create: `install.bat`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Create root directory structure**

```bash
mkdir -p backend/app/{engines,services,models,db,api}
mkdir -p backend/tests/{engines,services,api}
mkdir -p backend/app/engines
mkdir -p docs/plans
touch backend/app/__init__.py
touch backend/app/engines/__init__.py
touch backend/app/services/__init__.py
touch backend/app/models/__init__.py
touch backend/app/db/__init__.py
touch backend/app/api/__init__.py
touch backend/tests/__init__.py
```

**Step 2: Create docker-compose.yml**

```yaml
# docker-compose.yml
version: "3.9"
services:
  neo4j:
    image: neo4j:5
    container_name: lunar-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/lunar_password
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  neo4j_data:
```

**Step 3: Create .env.example**

```env
# .env.example
# LLM Providers — add your keys
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=

# Neo4j (matches docker-compose)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=lunar_password

# App
DEBUG=true
```

**Step 4: Create .gitignore**

```gitignore
# .gitignore
.env
__pycache__/
*.pyc
venv/
.venv/
node_modules/
dist/
*.db
.DS_Store
```

**Step 5: Create install.bat**

```bat
@echo off
echo === Project Lunar Installer ===

REM Check Docker
docker --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker Desktop not found. Install from https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

echo [1/5] Starting Neo4j via Docker...
docker-compose up -d neo4j
timeout /t 10 /nobreak >nul

echo [2/5] Setting up Python environment...
cd backend
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
cd ..

echo [3/5] Copying .env file...
IF NOT EXIST .env copy .env.example .env
echo      Edit .env to add your API keys!

echo [4/5] Installing frontend dependencies...
cd frontend
npm install
cd ..

echo [5/5] Done!
echo.
echo To start the app:
echo   Backend:  cd backend ^&^& venv\Scripts\activate ^&^& uvicorn app.main:app --reload --port 8000
echo   Frontend: cd frontend ^&^& npm run dev
echo.
echo Neo4j Browser: http://localhost:7474
echo App:           http://localhost:3000
pause
```

**Step 6: Commit**

```bash
git init
git add .
git commit -m "chore: initial project scaffold with docker and install script"
```

---

### Task 0.2: Backend Dependencies

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`

**Step 1: Create requirements.txt**

```txt
# backend/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.7.0
pydantic-settings==2.3.0
httpx==0.27.0
python-dotenv==1.0.1
litellm==1.43.0
instructor==1.4.0
graphiti-core==0.3.0
neo4j==5.22.0
aiofiles==23.2.1
tiktoken==0.7.0
python-multipart==0.0.9
```

```txt
# backend/requirements-dev.txt
pytest==8.2.0
pytest-asyncio==0.23.7
pytest-cov==5.0.0
httpx==0.27.0
```

**Step 2: Create backend/app/config.py**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "lunar_password"
    debug: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
```

**Step 3: Install and verify**

```bash
cd backend
python -m venv venv
venv/Scripts/activate  # Windows
pip install -r requirements.txt -r requirements-dev.txt
python -c "import fastapi, litellm, graphiti_core; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt backend/app/config.py
git commit -m "chore: add backend dependencies and config"
```

---

### Task 0.3: Frontend Scaffold

**Files:**
- Create: `frontend/` (Vite + React project)

**Step 1: Scaffold with Vite**

```bash
cd frontend
npm create vite@latest . -- --template react
npm install
npm install zustand axios react-router-dom lucide-react react-markdown framer-motion
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

**Step 2: Configure tailwind.config.js**

```js
// frontend/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

**Step 3: Update src/index.css**

```css
/* frontend/src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

**Step 4: Verify dev server starts**

```bash
npm run dev
```

Expected: Vite dev server on http://localhost:5173

**Step 5: Commit**

```bash
git add frontend/
git commit -m "chore: scaffold React/Vite frontend with Tailwind"
```

---

## Phase 1 — Data Layer

### Task 1.1: EventStore

The event store is the immutable append-only log that is the source of truth for all that happens in a campaign.

**Files:**
- Create: `backend/app/db/event_store.py`
- Create: `backend/tests/db/test_event_store.py`

**Step 1: Write failing tests**

```python
# backend/tests/db/test_event_store.py
import pytest
import tempfile
import os
from app.db.event_store import EventStore, Event, EventType


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_events.db")
    store = EventStore(db_path)
    yield store
    store.close()


def test_append_event(store):
    event = store.append(
        campaign_id="campaign-1",
        event_type=EventType.PLAYER_ACTION,
        payload={"text": "I open the door"},
        narrative_time_delta=60,  # 1 minute in story
        location="tavern",
        entities=["player", "door"],
    )
    assert event.id is not None
    assert event.event_type == EventType.PLAYER_ACTION


def test_get_recent_events(store):
    for i in range(5):
        store.append(
            campaign_id="campaign-1",
            event_type=EventType.PLAYER_ACTION,
            payload={"text": f"action {i}"},
            narrative_time_delta=60,
            location="tavern",
            entities=["player"],
        )
    events = store.get_recent(campaign_id="campaign-1", limit=3)
    assert len(events) == 3


def test_get_total_narrative_time(store):
    store.append("c1", EventType.PLAYER_ACTION, {}, 3600, "loc", [])  # 1 hour
    store.append("c1", EventType.WORLD_TICK, {}, 86400, "loc", [])   # 1 day
    total = store.get_total_narrative_time("c1")
    assert total == 3600 + 86400


def test_events_are_immutable(store):
    event = store.append("c1", EventType.PLAYER_ACTION, {"text": "hi"}, 0, "loc", [])
    # Attempting to modify should raise or have no effect
    with pytest.raises(AttributeError):
        event.payload = {"text": "modified"}
```

**Step 2: Run to verify failure**

```bash
cd backend
pytest tests/db/test_event_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.db.event_store'`

**Step 3: Implement EventStore**

```python
# backend/app/db/event_store.py
import sqlite3
import json
import uuid
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class EventType(str, Enum):
    PLAYER_ACTION = "PLAYER_ACTION"
    NARRATOR_RESPONSE = "NARRATOR_RESPONSE"
    WORLD_TICK = "WORLD_TICK"
    COMBAT_ACTION = "COMBAT_ACTION"
    COMBAT_RESULT = "COMBAT_RESULT"
    NPC_THOUGHT = "NPC_THOUGHT"
    JOURNAL_ENTRY = "JOURNAL_ENTRY"
    MEMORY_CRYSTAL = "MEMORY_CRYSTAL"
    TIMESKIP = "TIMESKIP"


@dataclass(frozen=True)
class Event:
    id: str
    campaign_id: str
    event_type: EventType
    payload: dict
    narrative_time_delta: int  # seconds in story time
    location: str
    entities: list[str]
    created_at: str


class EventStore:
    def __init__(self, db_path: str = "events.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                narrative_time_delta INTEGER NOT NULL DEFAULT 0,
                location TEXT NOT NULL DEFAULT '',
                entities TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_campaign ON events(campaign_id, created_at)"
        )
        self._conn.commit()

    def append(
        self,
        campaign_id: str,
        event_type: EventType,
        payload: dict,
        narrative_time_delta: int,
        location: str,
        entities: list[str],
    ) -> Event:
        event = Event(
            id=str(uuid.uuid4()),
            campaign_id=campaign_id,
            event_type=event_type,
            payload=payload,
            narrative_time_delta=narrative_time_delta,
            location=location,
            entities=entities,
            created_at=datetime.utcnow().isoformat(),
        )
        self._conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id,
                event.campaign_id,
                event.event_type.value,
                json.dumps(event.payload),
                event.narrative_time_delta,
                event.location,
                json.dumps(event.entities),
                event.created_at,
            ),
        )
        self._conn.commit()
        return event

    def get_recent(self, campaign_id: str, limit: int = 20) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
            (campaign_id, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in reversed(rows)]

    def get_total_narrative_time(self, campaign_id: str) -> int:
        row = self._conn.execute(
            "SELECT SUM(narrative_time_delta) FROM events WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        return row[0] or 0

    def _row_to_event(self, row) -> Event:
        return Event(
            id=row[0],
            campaign_id=row[1],
            event_type=EventType(row[2]),
            payload=json.loads(row[3]),
            narrative_time_delta=row[4],
            location=row[5],
            entities=json.loads(row[6]),
            created_at=row[7],
        )

    def close(self):
        self._conn.close()
```

**Step 4: Run tests**

```bash
pytest tests/db/test_event_store.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/db/event_store.py backend/tests/db/test_event_store.py
git commit -m "feat: add immutable EventStore with SQLite"
```

---

### Task 1.2: ScenarioStore

**Files:**
- Create: `backend/app/db/scenario_store.py`
- Create: `backend/tests/db/test_scenario_store.py`

**Step 1: Write failing tests**

```python
# backend/tests/db/test_scenario_store.py
import pytest
from app.db.scenario_store import ScenarioStore, Scenario, Campaign, StoryCard, StoryCardType


@pytest.fixture
def store(tmp_path):
    store = ScenarioStore(str(tmp_path / "test_scenarios.db"))
    yield store
    store.close()


def test_create_and_get_scenario(store):
    scenario = store.create_scenario(
        title="The Shattered Realm",
        description="A world broken by ancient magic",
        tone_instructions="Dark and gritty. High mortality. No mercy.",
        opening_narrative="You wake in the ruins of a city...",
        language="en",
    )
    fetched = store.get_scenario(scenario.id)
    assert fetched.title == "The Shattered Realm"


def test_add_story_card(store):
    scenario = store.create_scenario("Test", "", "", "", "en")
    card = store.add_story_card(
        scenario_id=scenario.id,
        card_type=StoryCardType.NPC,
        name="Mordain the Warlord",
        content={"personality": "brutal", "secret": "fears death", "power_level": 9},
    )
    assert card.id is not None
    cards = store.get_story_cards(scenario.id)
    assert len(cards) == 1
    assert cards[0].name == "Mordain the Warlord"


def test_create_campaign(store):
    scenario = store.create_scenario("Test", "", "", "", "en")
    campaign = store.create_campaign(scenario_id=scenario.id, player_name="Aria")
    assert campaign.id is not None
    assert campaign.scenario_id == scenario.id


def test_list_scenarios(store):
    store.create_scenario("Scenario A", "", "", "", "en")
    store.create_scenario("Scenario B", "", "", "", "en")
    scenarios = store.list_scenarios()
    assert len(scenarios) == 2
```

**Step 2: Run to verify failure**

```bash
pytest tests/db/test_scenario_store.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement ScenarioStore**

```python
# backend/app/db/scenario_store.py
import sqlite3
import json
import uuid
from datetime import datetime
from enum import Enum
from dataclasses import dataclass


class StoryCardType(str, Enum):
    NPC = "NPC"
    LOCATION = "LOCATION"
    FACTION = "FACTION"
    ITEM = "ITEM"
    LORE = "LORE"


@dataclass
class StoryCard:
    id: str
    scenario_id: str
    card_type: StoryCardType
    name: str
    content: dict
    created_at: str


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    tone_instructions: str
    opening_narrative: str
    language: str
    lore_text: str
    created_at: str


@dataclass
class Campaign:
    id: str
    scenario_id: str
    player_name: str
    created_at: str


class ScenarioStore:
    def __init__(self, db_path: str = "scenarios.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                tone_instructions TEXT NOT NULL DEFAULT '',
                opening_narrative TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                lore_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS story_cards (
                id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL REFERENCES scenarios(id),
                card_type TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL REFERENCES scenarios(id),
                player_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def create_scenario(
        self,
        title: str,
        description: str,
        tone_instructions: str,
        opening_narrative: str,
        language: str,
        lore_text: str = "",
    ) -> Scenario:
        scenario = Scenario(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            tone_instructions=tone_instructions,
            opening_narrative=opening_narrative,
            language=language,
            lore_text=lore_text,
            created_at=datetime.utcnow().isoformat(),
        )
        self._conn.execute(
            "INSERT INTO scenarios VALUES (?,?,?,?,?,?,?,?)",
            (scenario.id, scenario.title, scenario.description,
             scenario.tone_instructions, scenario.opening_narrative,
             scenario.language, scenario.lore_text, scenario.created_at),
        )
        self._conn.commit()
        return scenario

    def get_scenario(self, scenario_id: str) -> Scenario | None:
        row = self._conn.execute(
            "SELECT * FROM scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
        if not row:
            return None
        return Scenario(*row)

    def list_scenarios(self) -> list[Scenario]:
        rows = self._conn.execute(
            "SELECT * FROM scenarios ORDER BY created_at DESC"
        ).fetchall()
        return [Scenario(*r) for r in rows]

    def add_story_card(
        self,
        scenario_id: str,
        card_type: StoryCardType,
        name: str,
        content: dict,
    ) -> StoryCard:
        card = StoryCard(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            card_type=card_type,
            name=name,
            content=content,
            created_at=datetime.utcnow().isoformat(),
        )
        self._conn.execute(
            "INSERT INTO story_cards VALUES (?,?,?,?,?,?)",
            (card.id, card.scenario_id, card.card_type.value,
             card.name, json.dumps(card.content), card.created_at),
        )
        self._conn.commit()
        return card

    def get_story_cards(self, scenario_id: str) -> list[StoryCard]:
        rows = self._conn.execute(
            "SELECT * FROM story_cards WHERE scenario_id=?", (scenario_id,)
        ).fetchall()
        return [
            StoryCard(r[0], r[1], StoryCardType(r[2]), r[3], json.loads(r[4]), r[5])
            for r in rows
        ]

    def create_campaign(self, scenario_id: str, player_name: str) -> Campaign:
        campaign = Campaign(
            id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            player_name=player_name,
            created_at=datetime.utcnow().isoformat(),
        )
        self._conn.execute(
            "INSERT INTO campaigns VALUES (?,?,?,?)",
            (campaign.id, campaign.scenario_id, campaign.player_name, campaign.created_at),
        )
        self._conn.commit()
        return campaign

    def close(self):
        self._conn.close()
```

**Step 4: Run tests**

```bash
pytest tests/db/test_scenario_store.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/db/scenario_store.py backend/tests/db/test_scenario_store.py
git commit -m "feat: add ScenarioStore with scenarios, campaigns, and story cards"
```

---

### Task 1.3: GraphEngine (Graphiti + Neo4j)

> **Prerequisite:** Neo4j must be running. Run `docker-compose up -d neo4j` and wait ~15 seconds.

**Files:**
- Create: `backend/app/engines/graph_engine.py`
- Create: `backend/tests/engines/test_graph_engine.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_graph_engine.py
import pytest
import asyncio
from app.engines.graph_engine import GraphEngine, WorldNode, WorldNodeType, Relationship


@pytest.fixture
async def engine():
    eng = GraphEngine(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="lunar_password",
        campaign_id="test-campaign",
    )
    await eng.initialize()
    yield eng
    await eng.clear_campaign("test-campaign")
    await eng.close()


@pytest.mark.asyncio
async def test_add_npc_node(engine):
    node = await engine.add_node(
        node_type=WorldNodeType.NPC,
        name="Mordain",
        attributes={"power_level": 9, "personality": "brutal"},
    )
    assert node.id is not None
    assert node.name == "Mordain"


@pytest.mark.asyncio
async def test_add_relationship(engine):
    npc = await engine.add_node(WorldNodeType.NPC, "Mordain", {"power_level": 9})
    loc = await engine.add_node(WorldNodeType.LOCATION, "Iron Fortress", {})
    rel = await engine.add_relationship(
        source_id=npc.id,
        target_id=loc.id,
        rel_type="CONTROLS",
        strength=1.0,
    )
    assert rel is not None


@pytest.mark.asyncio
async def test_get_npc_power_level(engine):
    await engine.add_node(WorldNodeType.NPC, "WeakGoblin", {"power_level": 2})
    power = await engine.get_npc_power(name="WeakGoblin")
    assert power == 2


@pytest.mark.asyncio
async def test_query_neighbors(engine):
    npc = await engine.add_node(WorldNodeType.NPC, "King", {"power_level": 8})
    loc = await engine.add_node(WorldNodeType.LOCATION, "Throne Room", {})
    await engine.add_relationship(npc.id, loc.id, "RESIDES_IN", 1.0)
    neighbors = await engine.get_neighbors(npc.id)
    assert any(n.name == "Throne Room" for n in neighbors)
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_graph_engine.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement GraphEngine**

```python
# backend/app/engines/graph_engine.py
import uuid
from dataclasses import dataclass
from enum import Enum
from neo4j import AsyncGraphDatabase


class WorldNodeType(str, Enum):
    NPC = "NPC"
    LOCATION = "LOCATION"
    FACTION = "FACTION"
    ITEM = "ITEM"
    EVENT = "EVENT"


@dataclass
class WorldNode:
    id: str
    node_type: WorldNodeType
    name: str
    attributes: dict
    campaign_id: str


@dataclass
class Relationship:
    source_id: str
    target_id: str
    rel_type: str
    strength: float


class GraphEngine:
    def __init__(self, uri: str, user: str, password: str, campaign_id: str):
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        self.campaign_id = campaign_id

    async def initialize(self):
        async with self._driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (n:WorldNode) REQUIRE n.node_id IS UNIQUE"
            )

    async def add_node(
        self,
        node_type: WorldNodeType,
        name: str,
        attributes: dict,
    ) -> WorldNode:
        node_id = str(uuid.uuid4())
        async with self._driver.session() as session:
            await session.run(
                """
                CREATE (n:WorldNode {
                    node_id: $node_id,
                    node_type: $node_type,
                    name: $name,
                    campaign_id: $campaign_id,
                    attributes: $attributes
                })
                """,
                node_id=node_id,
                node_type=node_type.value,
                name=name,
                campaign_id=self.campaign_id,
                attributes=str(attributes),
            )
        return WorldNode(
            id=node_id,
            node_type=node_type,
            name=name,
            attributes=attributes,
            campaign_id=self.campaign_id,
        )

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        strength: float = 1.0,
    ) -> Relationship:
        async with self._driver.session() as session:
            await session.run(
                f"""
                MATCH (a:WorldNode {{node_id: $source_id}})
                MATCH (b:WorldNode {{node_id: $target_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                SET r.strength = $strength
                """,
                source_id=source_id,
                target_id=target_id,
                strength=strength,
            )
        return Relationship(source_id, target_id, rel_type, strength)

    async def get_npc_power(self, name: str) -> int:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (n:WorldNode {name: $name, campaign_id: $campaign_id})
                RETURN n.attributes AS attrs
                """,
                name=name,
                campaign_id=self.campaign_id,
            )
            record = await result.single()
            if not record:
                return 5  # default mid-level
            attrs = eval(record["attrs"])  # stored as str dict
            return attrs.get("power_level", 5)

    async def get_neighbors(self, node_id: str) -> list[WorldNode]:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (a:WorldNode {node_id: $node_id})-[r]-(b:WorldNode)
                RETURN b
                """,
                node_id=node_id,
            )
            nodes = []
            async for record in result:
                b = record["b"]
                nodes.append(WorldNode(
                    id=b["node_id"],
                    node_type=WorldNodeType(b["node_type"]),
                    name=b["name"],
                    attributes={},
                    campaign_id=b["campaign_id"],
                ))
            return nodes

    async def clear_campaign(self, campaign_id: str):
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:WorldNode {campaign_id: $campaign_id}) DETACH DELETE n",
                campaign_id=campaign_id,
            )

    async def close(self):
        await self._driver.close()
```

**Step 4: Run tests (Neo4j must be running)**

```bash
pytest tests/engines/test_graph_engine.py -v -s
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/engines/graph_engine.py backend/tests/engines/test_graph_engine.py
git commit -m "feat: add GraphEngine with Neo4j world graph and temporal relationships"
```

---

## Phase 2 — LLM Layer

### Task 2.1: LLMRouter

**Files:**
- Create: `backend/app/engines/llm_router.py`
- Create: `backend/tests/engines/test_llm_router.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_llm_router.py
import pytest
from unittest.mock import AsyncMock, patch
from app.engines.llm_router import LLMRouter, LLMConfig, LLMProvider


@pytest.fixture
def config():
    return LLMConfig(
        primary_provider=LLMProvider.DEEPSEEK,
        primary_model="deepseek-chat",
        temperature=0.8,
        max_tokens=2000,
    )


@pytest.fixture
def router(config):
    return LLMRouter(config)


def test_router_builds_model_string(router):
    model = router._build_model_string(LLMProvider.DEEPSEEK, "deepseek-chat")
    assert model == "deepseek/deepseek-chat"


def test_router_builds_openai_model(router):
    model = router._build_model_string(LLMProvider.OPENAI, "gpt-4o")
    assert model == "gpt-4o"


def test_router_builds_anthropic_model(router):
    model = router._build_model_string(LLMProvider.ANTHROPIC, "claude-sonnet-4-6")
    assert model == "anthropic/claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_complete_returns_text(router):
    with patch("app.engines.llm_router.litellm.acompletion") as mock_complete:
        mock_complete.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="Once upon a time..."))]
        )
        result = await router.complete(messages=[{"role": "user", "content": "Tell a story"}])
        assert result == "Once upon a time..."
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_llm_router.py -v
```

**Step 3: Implement LLMRouter**

```python
# backend/app/engines/llm_router.py
from enum import Enum
from dataclasses import dataclass, field
from typing import AsyncIterator
import litellm


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"


@dataclass
class LLMConfig:
    primary_provider: LLMProvider = LLMProvider.DEEPSEEK
    primary_model: str = "deepseek-chat"
    fallback_provider: LLMProvider | None = None
    fallback_model: str | None = None
    temperature: float = 0.8
    max_tokens: int = 2000


class LLMRouter:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_model_string(self, provider: LLMProvider, model: str) -> str:
        if provider == LLMProvider.OPENAI:
            return model
        return f"{provider.value}/{model}"

    async def complete(self, messages: list[dict], **kwargs) -> str:
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                **kwargs,
            )
            return response.choices[0].message.content
        except Exception:
            if self.config.fallback_provider and self.config.fallback_model:
                fallback_model = self._build_model_string(
                    self.config.fallback_provider, self.config.fallback_model
                )
                response = await litellm.acompletion(
                    model=fallback_model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    **kwargs,
                )
                return response.choices[0].message.content
            raise

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        model = self._build_model_string(
            self.config.primary_provider, self.config.primary_model
        )
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_llm_router.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/engines/llm_router.py backend/tests/engines/test_llm_router.py
git commit -m "feat: add LLMRouter with multi-provider support and fallback chain"
```

---

## Phase 3 — Memory & World Reactor

### Task 3.1: MemoryEngine (Crystal Memory)

**Files:**
- Create: `backend/app/engines/memory_engine.py`
- Create: `backend/tests/engines/test_memory_engine.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_memory_engine.py
import pytest
from unittest.mock import AsyncMock
from app.engines.memory_engine import MemoryEngine, MemoryCrystal, CrystalTier
from app.db.event_store import EventStore, EventType


@pytest.fixture
def event_store(tmp_path):
    store = EventStore(str(tmp_path / "events.db"))
    yield store
    store.close()


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Compressed memory crystal content.")
    return llm


@pytest.fixture
def memory_engine(event_store, mock_llm):
    return MemoryEngine(event_store=event_store, llm=mock_llm)


def test_raw_context_returns_recent_events(memory_engine, event_store):
    for i in range(5):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])
    ctx = memory_engine.get_raw_context("c1", limit=3)
    assert len(ctx) == 3


@pytest.mark.asyncio
async def test_crystallize_creates_short_crystal(memory_engine, event_store):
    for i in range(25):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])
    crystal = await memory_engine.crystallize("c1", tier=CrystalTier.SHORT)
    assert crystal.content == "Compressed memory crystal content."
    assert crystal.tier == CrystalTier.SHORT


def test_build_context_window(memory_engine, event_store):
    for i in range(5):
        event_store.append("c1", EventType.PLAYER_ACTION, {"text": f"action {i}"}, 60, "loc", [])
    context = memory_engine.build_context_window("c1")
    assert "action" in context
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_memory_engine.py -v
```

**Step 3: Implement MemoryEngine**

```python
# backend/app/engines/memory_engine.py
from dataclasses import dataclass, field
from enum import Enum
from app.db.event_store import EventStore, Event, EventType


class CrystalTier(str, Enum):
    SHORT = "SHORT"   # last 5 sessions compressed
    LONG = "LONG"     # permanent extracted facts


@dataclass
class MemoryCrystal:
    campaign_id: str
    tier: CrystalTier
    content: str
    event_count: int


class MemoryEngine:
    RAW_LIMIT = 20
    CRYSTALLIZE_THRESHOLD = 20

    def __init__(self, event_store: EventStore, llm):
        self._store = event_store
        self._llm = llm
        self._crystals: dict[str, list[MemoryCrystal]] = {}

    def get_raw_context(self, campaign_id: str, limit: int = RAW_LIMIT) -> list[Event]:
        return self._store.get_recent(campaign_id, limit=limit)

    async def crystallize(self, campaign_id: str, tier: CrystalTier) -> MemoryCrystal:
        events = self._store.get_recent(campaign_id, limit=50)
        events_text = "\n".join(
            f"[{e.event_type.value}] {e.payload.get('text', '')}" for e in events
        )
        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a memory crystallizer. Compress the following events into a "
                    "dense, factual summary preserving all important details, relationships, "
                    "decisions, and world changes. Be concise but complete."
                ),
            },
            {"role": "user", "content": events_text},
        ]
        compressed = await self._llm.complete(messages=prompt)
        crystal = MemoryCrystal(
            campaign_id=campaign_id,
            tier=tier,
            content=compressed,
            event_count=len(events),
        )
        if campaign_id not in self._crystals:
            self._crystals[campaign_id] = []
        self._crystals[campaign_id].append(crystal)
        return crystal

    def get_crystals(self, campaign_id: str) -> list[MemoryCrystal]:
        return self._crystals.get(campaign_id, [])

    def build_context_window(self, campaign_id: str) -> str:
        parts = []
        crystals = self.get_crystals(campaign_id)
        if crystals:
            parts.append("=== LONG-TERM MEMORY ===")
            for c in crystals:
                parts.append(c.content)
        raw = self.get_raw_context(campaign_id)
        if raw:
            parts.append("=== RECENT EVENTS ===")
            for e in raw:
                text = e.payload.get("text", "")
                if text:
                    parts.append(f"[{e.event_type.value}] {text}")
        return "\n".join(parts)
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_memory_engine.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/engines/memory_engine.py backend/tests/engines/test_memory_engine.py
git commit -m "feat: add MemoryEngine with 3-tier crystal memory system"
```

---

### Task 3.2: WorldReactor

**Files:**
- Create: `backend/app/engines/world_reactor.py`
- Create: `backend/tests/engines/test_world_reactor.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_world_reactor.py
import pytest
from unittest.mock import AsyncMock
from app.engines.world_reactor import WorldReactor, TickType


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Minor shifts in NPC mood.")
    return llm


@pytest.fixture
def reactor(mock_llm):
    return WorldReactor(llm=mock_llm)


def test_classify_tick_micro(reactor):
    tick = reactor.classify_tick(narrative_seconds=300)  # 5 minutes
    assert tick == TickType.MICRO


def test_classify_tick_minor(reactor):
    tick = reactor.classify_tick(narrative_seconds=3600)  # 1 hour
    assert tick == TickType.MINOR


def test_classify_tick_major(reactor):
    tick = reactor.classify_tick(narrative_seconds=604800)  # 1 week
    assert tick == TickType.MAJOR


def test_classify_tick_heavy(reactor):
    tick = reactor.classify_tick(narrative_seconds=2592000)  # 30 days
    assert tick == TickType.HEAVY


@pytest.mark.asyncio
async def test_process_tick_returns_world_changes(reactor):
    changes = await reactor.process_tick(
        campaign_id="c1",
        narrative_seconds=3600,
        world_context="The king is ill. The warlord eyes the throne.",
    )
    assert isinstance(changes, str)
    assert len(changes) > 0
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_world_reactor.py -v
```

**Step 3: Implement WorldReactor**

```python
# backend/app/engines/world_reactor.py
from enum import Enum


class TickType(str, Enum):
    MICRO = "MICRO"       # < 1 hour
    MINOR = "MINOR"       # 1 hour – 1 day
    MODERATE = "MODERATE" # 1 day – 1 week
    MAJOR = "MAJOR"       # 1 week – 1 month
    HEAVY = "HEAVY"       # > 1 month


TICK_THRESHOLDS = {
    TickType.MICRO: 3600,
    TickType.MINOR: 86400,
    TickType.MODERATE: 604800,
    TickType.MAJOR: 2592000,
    TickType.HEAVY: float("inf"),
}

TICK_PROMPTS = {
    TickType.MICRO: "Describe minor mood or state shifts for nearby NPCs. Be brief.",
    TickType.MINOR: "Describe NPC movements and minor news spreading through the region.",
    TickType.MODERATE: "Describe faction decisions, rumors, and moderate world changes.",
    TickType.MAJOR: "Describe political shifts, NPC life events, and significant world changes.",
    TickType.HEAVY: "Describe wars, deaths, new alliances, and major transformations in the world.",
}


class WorldReactor:
    def __init__(self, llm):
        self._llm = llm

    def classify_tick(self, narrative_seconds: int) -> TickType:
        if narrative_seconds < TICK_THRESHOLDS[TickType.MICRO]:
            return TickType.MICRO
        if narrative_seconds < TICK_THRESHOLDS[TickType.MINOR]:
            return TickType.MINOR
        if narrative_seconds < TICK_THRESHOLDS[TickType.MODERATE]:
            return TickType.MODERATE
        if narrative_seconds < TICK_THRESHOLDS[TickType.MAJOR]:
            return TickType.MAJOR
        return TickType.HEAVY

    async def process_tick(
        self,
        campaign_id: str,
        narrative_seconds: int,
        world_context: str,
    ) -> str:
        tick_type = self.classify_tick(narrative_seconds)
        if tick_type == TickType.MICRO:
            return ""  # No visible world change for micro ticks

        instruction = TICK_PROMPTS[tick_type]
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a world simulation engine. {instruction} "
                    "Write only the world changes as narrative facts, no dialogue."
                ),
            },
            {
                "role": "user",
                "content": f"World context:\n{world_context}\n\nTime elapsed: {narrative_seconds} seconds.",
            },
        ]
        return await self._llm.complete(messages=messages)
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_world_reactor.py -v
```

Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/app/engines/world_reactor.py backend/tests/engines/test_world_reactor.py
git commit -m "feat: add WorldReactor with narrative time tick classification and LLM-driven world simulation"
```

---

## Phase 4 — Narrative & Combat

### Task 4.1: CombatEngine

**Files:**
- Create: `backend/app/engines/combat_engine.py`
- Create: `backend/tests/engines/test_combat_engine.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_combat_engine.py
import pytest
from unittest.mock import AsyncMock
from app.engines.combat_engine import (
    CombatEngine, CombatOutcome, ActionEvaluation, AntiGriefingResult
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def engine(mock_llm):
    return CombatEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_evaluate_creative_action_high_score(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"coherence": 9, "creativity": 8, "context": 8}')
    eval_result = await engine.evaluate_action(
        action="I feint left then roll under his guard and drive my elbow into his knee",
        npc_name="Guard",
        npc_power=5,
    )
    assert eval_result.final_quality > 7.0


@pytest.mark.asyncio
async def test_evaluate_simple_action_low_score(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"coherence": 7, "creativity": 2, "context": 5}')
    eval_result = await engine.evaluate_action(
        action="I attack him",
        npc_name="War Veteran",
        npc_power=9,
    )
    assert eval_result.final_quality < 6.0


@pytest.mark.asyncio
async def test_anti_griefing_rejects_meta_action(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"is_meta": true, "is_physically_impossible": false}')
    result = await engine.anti_griefing_check(
        "I win the fight because I am the protagonist and cannot lose"
    )
    assert result.rejected is True


@pytest.mark.asyncio
async def test_roll_outcome_high_quality_high_chance(engine):
    # quality 9/10, difficulty 3/10 → very high success chance
    outcome = engine.roll_outcome(action_quality=9.0, npc_power=3)
    assert outcome in [CombatOutcome.SUCCESS, CombatOutcome.CRIT_SUCCESS]


@pytest.mark.asyncio
async def test_roll_outcome_low_quality_hard_npc(engine):
    # Run 50 times, low quality vs high power should never crit success
    for _ in range(50):
        outcome = engine.roll_outcome(action_quality=2.0, npc_power=10)
        assert outcome != CombatOutcome.CRIT_SUCCESS
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_combat_engine.py -v
```

**Step 3: Implement CombatEngine**

```python
# backend/app/engines/combat_engine.py
import json
import random
from dataclasses import dataclass
from enum import Enum


class CombatOutcome(str, Enum):
    CRIT_FAIL = "CRIT_FAIL"
    FAIL = "FAIL"
    SUCCESS = "SUCCESS"
    CRIT_SUCCESS = "CRIT_SUCCESS"


@dataclass
class ActionEvaluation:
    coherence: float
    creativity: float
    context: float
    final_quality: float


@dataclass
class AntiGriefingResult:
    rejected: bool
    reason: str = ""


class CombatEngine:
    def __init__(self, llm):
        self._llm = llm

    async def anti_griefing_check(self, action: str) -> AntiGriefingResult:
        messages = [
            {
                "role": "system",
                "content": (
                    "Analyze this combat action for griefing attempts. "
                    "Return JSON: {\"is_meta\": bool, \"is_physically_impossible\": bool}. "
                    "is_meta=true if player claims victory by narrative fiat. "
                    "is_physically_impossible=true if action defies physics completely."
                ),
            },
            {"role": "user", "content": action},
        ]
        raw = await self._llm.complete(messages=messages)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return AntiGriefingResult(rejected=False)

        if data.get("is_meta"):
            return AntiGriefingResult(rejected=True, reason="Meta-gaming attempt detected.")
        if data.get("is_physically_impossible"):
            return AntiGriefingResult(rejected=True, reason="Physically impossible action.")
        return AntiGriefingResult(rejected=False)

    async def evaluate_action(
        self,
        action: str,
        npc_name: str,
        npc_power: int,
    ) -> ActionEvaluation:
        messages = [
            {
                "role": "system",
                "content": (
                    "Evaluate this combat action. Score each from 0-10. "
                    "coherence: physical/logical feasibility. "
                    "creativity: originality and tactical thinking (NOT text length). "
                    "context: appropriateness to the situation. "
                    "Return ONLY JSON: {\"coherence\": N, \"creativity\": N, \"context\": N}"
                ),
            },
            {
                "role": "user",
                "content": f"Action: {action}\nOpponent: {npc_name} (power {npc_power}/10)",
            },
        ]
        raw = await self._llm.complete(messages=messages)
        try:
            data = json.loads(raw)
            coherence = float(data.get("coherence", 5))
            creativity = float(data.get("creativity", 5))
            context = float(data.get("context", 5))
        except (json.JSONDecodeError, ValueError):
            coherence = creativity = context = 5.0

        final_quality = coherence * 0.4 + creativity * 0.4 + context * 0.2
        return ActionEvaluation(
            coherence=coherence,
            creativity=creativity,
            context=context,
            final_quality=final_quality,
        )

    def roll_outcome(self, action_quality: float, npc_power: int) -> CombatOutcome:
        """
        action_quality: 0-10
        npc_power: 1-10
        Returns outcome based on combined probability.
        """
        # Normalize to 0-1
        quality_norm = action_quality / 10.0
        difficulty_norm = npc_power / 10.0

        # Success probability: quality heavily weighted, difficulty reduces it
        success_prob = quality_norm * 0.7 + (1 - difficulty_norm) * 0.3

        roll = random.random()

        if roll < 0.05 * (1 - quality_norm):          # Crit fail — weighted by low quality
            return CombatOutcome.CRIT_FAIL
        if roll < (1 - success_prob) * 0.6:
            return CombatOutcome.FAIL
        if roll > 0.9 + quality_norm * 0.05 - difficulty_norm * 0.03:
            return CombatOutcome.CRIT_SUCCESS
        return CombatOutcome.SUCCESS
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_combat_engine.py -v
```

Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/app/engines/combat_engine.py backend/tests/engines/test_combat_engine.py
git commit -m "feat: add CombatEngine with creativity evaluation, anti-griefing, and outcome rolling"
```

---

### Task 4.2: NarratorEngine

**Files:**
- Create: `backend/app/engines/narrator_engine.py`
- Create: `backend/tests/engines/test_narrator_engine.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_narrator_engine.py
import pytest
from unittest.mock import AsyncMock
from app.engines.narrator_engine import NarratorEngine, NarrativeMode


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def engine(mock_llm):
    return NarratorEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_detect_narrative_mode_combat(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"mode": "COMBAT", "ambush": false, "narrative_time_seconds": 0}')
    mode, meta = await engine.detect_mode("I draw my sword and charge at the bandit!")
    assert mode == NarrativeMode.COMBAT
    assert meta["ambush"] is False


@pytest.mark.asyncio
async def test_detect_narrative_mode_narrative(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"mode": "NARRATIVE", "ambush": false, "narrative_time_seconds": 3600}')
    mode, meta = await engine.detect_mode("I walk toward the tavern and ask the barkeep about rumors")
    assert mode == NarrativeMode.NARRATIVE


@pytest.mark.asyncio
async def test_detect_meta_mode(engine, mock_llm):
    mock_llm.complete = AsyncMock(return_value='{"mode": "META", "ambush": false, "narrative_time_seconds": 0}')
    mode, meta = await engine.detect_mode("Can you make the story more dramatic?")
    assert mode == NarrativeMode.META


def test_build_system_prompt(engine):
    prompt = engine.build_system_prompt(
        tone_instructions="Dark and gritty.",
        memory_context="The player betrayed the king.",
        language="en",
    )
    assert "Dark and gritty" in prompt
    assert "betrayed the king" in prompt
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_narrator_engine.py -v
```

**Step 3: Implement NarratorEngine**

```python
# backend/app/engines/narrator_engine.py
import json
from enum import Enum
from typing import AsyncIterator


class NarrativeMode(str, Enum):
    NARRATIVE = "NARRATIVE"
    COMBAT = "COMBAT"
    META = "META"


class NarratorEngine:
    def __init__(self, llm):
        self._llm = llm

    async def detect_mode(self, player_input: str) -> tuple[NarrativeMode, dict]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the player's action. Return JSON: "
                    "{\"mode\": \"NARRATIVE|COMBAT|META\", \"ambush\": bool, \"narrative_time_seconds\": int}. "
                    "COMBAT if action initiates or continues a fight. "
                    "META if player speaks to the AI narrator directly. "
                    "NARRATIVE for everything else. "
                    "ambush=true only if the NPC attacks player by surprise. "
                    "narrative_time_seconds: estimated story time this action takes."
                ),
            },
            {"role": "user", "content": player_input},
        ]
        raw = await self._llm.complete(messages=messages)
        try:
            data = json.loads(raw)
            mode = NarrativeMode(data.get("mode", "NARRATIVE"))
            return mode, data
        except (json.JSONDecodeError, ValueError):
            return NarrativeMode.NARRATIVE, {"ambush": False, "narrative_time_seconds": 60}

    def build_system_prompt(
        self,
        tone_instructions: str,
        memory_context: str,
        language: str,
    ) -> str:
        lang_instruction = (
            "Respond in English." if language == "en"
            else f"Respond in the language: {language}."
        )
        return (
            f"You are an AI narrator for an interactive RPG story. {lang_instruction}\n\n"
            f"TONE AND STYLE:\n{tone_instructions}\n\n"
            f"WORLD MEMORY:\n{memory_context}\n\n"
            "Rules:\n"
            "- Write immersive, evocative prose. Never break character.\n"
            "- React meaningfully to player choices. Consequences matter.\n"
            "- The world is alive. NPCs have their own agendas.\n"
            "- Match the established tone consistently.\n"
            "- Do NOT summarize. Narrate in present tense."
        )

    async def stream_narrative(
        self,
        player_input: str,
        system_prompt: str,
        history: list[dict],
    ) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])  # Keep last 10 exchanges
        messages.append({"role": "user", "content": player_input})
        async for chunk in self._llm.stream(messages=messages):
            yield chunk
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_narrator_engine.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/app/engines/narrator_engine.py backend/tests/engines/test_narrator_engine.py
git commit -m "feat: add NarratorEngine with mode detection and SSE-ready streaming"
```

---

## Phase 5 — Generation & Journal

### Task 5.1: PlotGenerator

**Files:**
- Create: `backend/app/engines/plot_generator.py`
- Create: `backend/tests/engines/test_plot_generator.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_plot_generator.py
import pytest
from unittest.mock import AsyncMock
from app.engines.plot_generator import PlotGenerator, GeneratedNPC, RandomEvent


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def generator(mock_llm):
    return PlotGenerator(llm=mock_llm)


@pytest.mark.asyncio
async def test_generate_npc(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json_npc())
    npc = await generator.generate_npc(world_context="A medieval kingdom under siege")
    assert npc.name is not None
    assert 1 <= npc.power_level <= 10
    assert npc.secret is not None


@pytest.mark.asyncio
async def test_generate_random_event(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value=json_event())
    event = await generator.generate_random_event(
        location="Crossroads",
        world_context="War is coming",
        narrative_time=86400,
    )
    assert event.title is not None
    assert event.description is not None


@pytest.mark.asyncio
async def test_generate_plot_arc(generator, mock_llm):
    mock_llm.complete = AsyncMock(return_value="The merchant's stolen ledger holds the key...")
    arc = await generator.generate_plot_arc(world_context="Trade city")
    assert isinstance(arc, str)
    assert len(arc) > 10


def json_npc():
    import json
    return json.dumps({
        "name": "Seraphine the Pale",
        "personality": "Calculating and cold",
        "power_level": 7,
        "secret": "She is the king's illegitimate daughter",
        "goal": "Claim the throne without bloodshed",
        "appearance": "Tall, white hair, silver eyes",
    })


def json_event():
    import json
    return json.dumps({
        "title": "The Wandering Merchant",
        "description": "A merchant arrives with goods from the north and unsettling rumors.",
        "choices": ["Buy from him", "Interrogate him", "Ignore him"],
    })
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_plot_generator.py -v
```

**Step 3: Implement PlotGenerator**

```python
# backend/app/engines/plot_generator.py
import json
from dataclasses import dataclass


@dataclass
class GeneratedNPC:
    name: str
    personality: str
    power_level: int
    secret: str
    goal: str
    appearance: str


@dataclass
class RandomEvent:
    title: str
    description: str
    choices: list[str]


class PlotGenerator:
    def __init__(self, llm):
        self._llm = llm

    async def generate_npc(self, world_context: str) -> GeneratedNPC:
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a compelling NPC for this world. "
                    "Return JSON: {name, personality, power_level (1-10), secret, goal, appearance}."
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}"},
        ]
        raw = await self._llm.complete(messages=messages)
        data = json.loads(raw)
        return GeneratedNPC(
            name=data["name"],
            personality=data["personality"],
            power_level=int(data["power_level"]),
            secret=data["secret"],
            goal=data["goal"],
            appearance=data["appearance"],
        )

    async def generate_random_event(
        self,
        location: str,
        world_context: str,
        narrative_time: int,
    ) -> RandomEvent:
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a contextually appropriate random event for the player to encounter. "
                    "Return JSON: {title, description, choices: [str, str, str]}."
                ),
            },
            {
                "role": "user",
                "content": f"Location: {location}\nWorld context: {world_context}\nTime elapsed: {narrative_time}s",
            },
        ]
        raw = await self._llm.complete(messages=messages)
        data = json.loads(raw)
        return RandomEvent(
            title=data["title"],
            description=data["description"],
            choices=data.get("choices", []),
        )

    async def generate_plot_arc(self, world_context: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a compelling plot arc hook for a new quest or story branch. "
                    "Write 2-3 sentences as narrative prose, no lists."
                ),
            },
            {"role": "user", "content": f"World context:\n{world_context}"},
        ]
        return await self._llm.complete(messages=messages)
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_plot_generator.py -v
```

Expected: 3 passed

**Step 5: Commit**

```bash
git add backend/app/engines/plot_generator.py backend/tests/engines/test_plot_generator.py
git commit -m "feat: add PlotGenerator with NPC, event, and plot arc generation"
```

---

### Task 5.2: JournalEngine

**Files:**
- Create: `backend/app/engines/journal_engine.py`
- Create: `backend/tests/engines/test_journal_engine.py`

**Step 1: Write failing tests**

```python
# backend/tests/engines/test_journal_engine.py
import pytest
from unittest.mock import AsyncMock
from app.engines.journal_engine import JournalEngine, JournalEntry, JournalCategory


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def engine(mock_llm):
    return JournalEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_evaluate_relevant_event(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"relevant": true, "category": "DECISION", "summary": "Player refused the king\'s offer."}'
    )
    entry = await engine.evaluate_and_log(
        campaign_id="c1",
        narrative_text="The king offers you gold to betray your friends. You refuse.",
    )
    assert entry is not None
    assert entry.category == JournalCategory.DECISION


@pytest.mark.asyncio
async def test_skip_irrelevant_event(engine, mock_llm):
    mock_llm.complete = AsyncMock(
        return_value='{"relevant": false, "category": null, "summary": null}'
    )
    entry = await engine.evaluate_and_log(
        campaign_id="c1",
        narrative_text="You walk down a dusty road.",
    )
    assert entry is None


def test_get_journal(engine):
    engine._journals["c1"] = [
        JournalEntry("c1", JournalCategory.DISCOVERY, "Found hidden cave", "2026-01-01")
    ]
    entries = engine.get_journal("c1")
    assert len(entries) == 1
    assert entries[0].category == JournalCategory.DISCOVERY
```

**Step 2: Run to verify failure**

```bash
pytest tests/engines/test_journal_engine.py -v
```

**Step 3: Implement JournalEngine**

```python
# backend/app/engines/journal_engine.py
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JournalCategory(str, Enum):
    DISCOVERY = "DISCOVERY"
    RELATIONSHIP_CHANGE = "RELATIONSHIP_CHANGE"
    COMBAT = "COMBAT"
    DECISION = "DECISION"
    WORLD_EVENT = "WORLD_EVENT"


@dataclass
class JournalEntry:
    campaign_id: str
    category: JournalCategory
    summary: str
    created_at: str


class JournalEngine:
    def __init__(self, llm):
        self._llm = llm
        self._journals: dict[str, list[JournalEntry]] = {}

    async def evaluate_and_log(
        self,
        campaign_id: str,
        narrative_text: str,
    ) -> JournalEntry | None:
        messages = [
            {
                "role": "system",
                "content": (
                    "Determine if this narrative moment is significant enough for a player journal. "
                    "Significant = discovery, relationship change, combat, major decision, world event. "
                    "Return JSON: {\"relevant\": bool, \"category\": \"DISCOVERY|RELATIONSHIP_CHANGE|COMBAT|DECISION|WORLD_EVENT|null\", \"summary\": str|null}"
                ),
            },
            {"role": "user", "content": narrative_text},
        ]
        raw = await self._llm.complete(messages=messages)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        if not data.get("relevant") or not data.get("category"):
            return None

        entry = JournalEntry(
            campaign_id=campaign_id,
            category=JournalCategory(data["category"]),
            summary=data["summary"],
            created_at=datetime.utcnow().isoformat(),
        )
        if campaign_id not in self._journals:
            self._journals[campaign_id] = []
        self._journals[campaign_id].append(entry)
        return entry

    def get_journal(self, campaign_id: str) -> list[JournalEntry]:
        return self._journals.get(campaign_id, [])

    def get_by_category(self, campaign_id: str, category: JournalCategory) -> list[JournalEntry]:
        return [e for e in self.get_journal(campaign_id) if e.category == category]
```

**Step 4: Run tests**

```bash
pytest tests/engines/test_journal_engine.py -v
```

Expected: 3 passed

**Step 5: Commit**

```bash
git add backend/app/engines/journal_engine.py backend/tests/engines/test_journal_engine.py
git commit -m "feat: add JournalEngine with auto-detection and categorization of significant events"
```

---

## Phase 6 — Scenario Service & Lore Extraction

### Task 6.1: ScenarioService + Lore Extraction

**Files:**
- Create: `backend/app/services/scenario_service.py`
- Create: `backend/tests/services/test_scenario_service.py`

**Step 1: Write failing tests**

```python
# backend/tests/services/test_scenario_service.py
import pytest
from unittest.mock import AsyncMock
from app.services.scenario_service import ScenarioService
from app.db.scenario_store import ScenarioStore, StoryCardType


@pytest.fixture
def store(tmp_path):
    s = ScenarioStore(str(tmp_path / "scenarios.db"))
    yield s
    s.close()


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def service(store, mock_llm):
    return ScenarioService(store=store, llm=mock_llm)


@pytest.mark.asyncio
async def test_extract_lore_creates_story_cards(service, mock_llm):
    mock_llm.complete = AsyncMock(return_value=lore_extraction_response())
    scenario = service.store.create_scenario("Test", "", "", "", "en")
    cards = await service.extract_lore_to_cards(
        scenario_id=scenario.id,
        lore_text="King Aldric rules from the Iron Citadel. He fears the witch Seraphine.",
    )
    assert len(cards) >= 2
    names = [c.name for c in cards]
    assert any("Aldric" in n for n in names)


def lore_extraction_response():
    import json
    return json.dumps([
        {"type": "NPC", "name": "King Aldric", "content": {"personality": "noble", "power_level": 8, "secret": "fears Seraphine"}},
        {"type": "NPC", "name": "Seraphine", "content": {"personality": "mysterious", "power_level": 9, "secret": "unknown origin"}},
        {"type": "LOCATION", "name": "Iron Citadel", "content": {"description": "Fortress of the king"}},
    ])
```

**Step 2: Run to verify failure**

```bash
pytest tests/services/test_scenario_service.py -v
```

**Step 3: Implement ScenarioService**

```python
# backend/app/services/scenario_service.py
import json
from app.db.scenario_store import ScenarioStore, StoryCard, StoryCardType


class ScenarioService:
    def __init__(self, store: ScenarioStore, llm):
        self.store = store
        self._llm = llm

    async def extract_lore_to_cards(
        self,
        scenario_id: str,
        lore_text: str,
    ) -> list[StoryCard]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract all named entities from this world lore text. "
                    "Return a JSON array of objects: "
                    "[{\"type\": \"NPC|LOCATION|FACTION|ITEM\", \"name\": str, \"content\": {}}]. "
                    "For NPCs include: personality, power_level (1-10), secret. "
                    "For LOCATIONs include: description. "
                    "For FACTIONs include: goals, power_level."
                ),
            },
            {"role": "user", "content": lore_text},
        ]
        raw = await self._llm.complete(messages=messages)
        try:
            entities = json.loads(raw)
        except json.JSONDecodeError:
            return []

        cards = []
        for entity in entities:
            try:
                card_type = StoryCardType(entity["type"])
                card = self.store.add_story_card(
                    scenario_id=scenario_id,
                    card_type=card_type,
                    name=entity["name"],
                    content=entity.get("content", {}),
                )
                cards.append(card)
            except (KeyError, ValueError):
                continue
        return cards
```

**Step 4: Run tests**

```bash
pytest tests/services/test_scenario_service.py -v
```

Expected: 1 passed

**Step 5: Commit**

```bash
git add backend/app/services/scenario_service.py backend/tests/services/test_scenario_service.py
git commit -m "feat: add ScenarioService with Fabula-inspired lore extraction to story cards"
```

---

## Phase 7 — FastAPI Routes

### Task 7.1: Main App & Game Session Route

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/api/routes_scenarios.py`
- Create: `backend/app/api/routes_game.py`
- Create: `backend/tests/api/test_routes_scenarios.py`

**Step 1: Create backend/app/main.py**

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes_scenarios import router as scenarios_router
from app.api.routes_game import router as game_router

app = FastAPI(title="Project Lunar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scenarios_router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(game_router, prefix="/api/game", tags=["game"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
```

**Step 2: Write failing API tests**

```python
# backend/tests/api/test_routes_scenarios.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_scenario():
    r = client.post("/api/scenarios/", json={
        "title": "Dark Realm",
        "description": "A world of shadows",
        "tone_instructions": "Dark and hopeless",
        "opening_narrative": "You wake in darkness...",
        "language": "en",
    })
    assert r.status_code == 201
    assert r.json()["title"] == "Dark Realm"


def test_list_scenarios():
    r = client.get("/api/scenarios/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

**Step 3: Run to verify failure**

```bash
pytest tests/api/test_routes_scenarios.py -v
```

**Step 4: Implement routes**

```python
# backend/app/api/routes_scenarios.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.scenario_store import ScenarioStore, StoryCardType

router = APIRouter()
_store = ScenarioStore()


class CreateScenarioRequest(BaseModel):
    title: str
    description: str = ""
    tone_instructions: str = ""
    opening_narrative: str = ""
    language: str = "en"
    lore_text: str = ""


class AddStoryCardRequest(BaseModel):
    card_type: StoryCardType
    name: str
    content: dict = {}


@router.post("/", status_code=201)
def create_scenario(req: CreateScenarioRequest):
    scenario = _store.create_scenario(
        title=req.title,
        description=req.description,
        tone_instructions=req.tone_instructions,
        opening_narrative=req.opening_narrative,
        language=req.language,
        lore_text=req.lore_text,
    )
    return scenario.__dict__


@router.get("/")
def list_scenarios():
    return [s.__dict__ for s in _store.list_scenarios()]


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str):
    scenario = _store.get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario.__dict__


@router.post("/{scenario_id}/story-cards", status_code=201)
def add_story_card(scenario_id: str, req: AddStoryCardRequest):
    card = _store.add_story_card(scenario_id, req.card_type, req.name, req.content)
    return card.__dict__


@router.get("/{scenario_id}/story-cards")
def get_story_cards(scenario_id: str):
    return [c.__dict__ for c in _store.get_story_cards(scenario_id)]
```

```python
# backend/app/api/routes_game.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class PlayerActionRequest(BaseModel):
    campaign_id: str
    action: str
    action_type: str = "DO"  # DO | SAY | CONTINUE | META


@router.post("/action")
async def player_action(req: PlayerActionRequest):
    # Placeholder — wired up in Phase 8
    return {"status": "ok", "message": "Engine not yet connected"}
```

**Step 5: Run tests**

```bash
pytest tests/api/test_routes_scenarios.py -v
```

Expected: 3 passed

**Step 6: Commit**

```bash
git add backend/app/main.py backend/app/api/ backend/tests/api/
git commit -m "feat: add FastAPI app with scenario and game routes"
```

---

## Phase 8 — Engine Wiring & SSE Game Loop

### Task 8.1: GameSession — Wire All Engines

**Files:**
- Create: `backend/app/services/game_session.py`
- Create: `backend/tests/services/test_game_session.py`

**Step 1: Write failing tests**

```python
# backend/tests/services/test_game_session.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.game_session import GameSession


@pytest.fixture
def mock_engines():
    return {
        "narrator": MagicMock(
            detect_mode=AsyncMock(return_value=("NARRATIVE", {"narrative_time_seconds": 60, "ambush": False})),
            build_system_prompt=MagicMock(return_value="system prompt"),
            stream_narrative=AsyncMock(return_value=aiter(["Once", " upon", " a time"])),
        ),
        "memory": MagicMock(
            build_context_window=MagicMock(return_value="memory context"),
        ),
        "world_reactor": MagicMock(
            process_tick=AsyncMock(return_value=""),
        ),
        "journal": MagicMock(
            evaluate_and_log=AsyncMock(return_value=None),
        ),
        "event_store": MagicMock(
            append=MagicMock(),
        ),
    }


@pytest.mark.asyncio
async def test_process_narrative_action(mock_engines):
    session = GameSession(
        campaign_id="c1",
        scenario_tone="dark",
        language="en",
        **mock_engines,
    )
    chunks = []
    async for chunk in session.process_action("I walk to the tavern"):
        chunks.append(chunk)
    assert len(chunks) > 0


async def aiter(items):
    for item in items:
        yield item
```

**Step 2: Implement GameSession**

```python
# backend/app/services/game_session.py
from typing import AsyncIterator
from app.db.event_store import EventType
from app.engines.narrator_engine import NarrativeMode


class GameSession:
    def __init__(
        self,
        campaign_id: str,
        scenario_tone: str,
        language: str,
        narrator,
        memory,
        world_reactor,
        journal,
        event_store,
        combat_engine=None,
        graph_engine=None,
    ):
        self.campaign_id = campaign_id
        self.scenario_tone = scenario_tone
        self.language = language
        self._narrator = narrator
        self._memory = memory
        self._world_reactor = world_reactor
        self._journal = journal
        self._event_store = event_store
        self._combat = combat_engine
        self._graph = graph_engine
        self._history: list[dict] = []

    async def process_action(self, player_input: str) -> AsyncIterator[str]:
        mode, meta = await self._narrator.detect_mode(player_input)
        narrative_time = meta.get("narrative_time_seconds", 60)

        self._event_store.append(
            campaign_id=self.campaign_id,
            event_type=EventType.PLAYER_ACTION,
            payload={"text": player_input, "mode": mode},
            narrative_time_delta=narrative_time,
            location="current",
            entities=["player"],
        )

        if mode == NarrativeMode.COMBAT and self._combat:
            async for chunk in self._handle_combat(player_input, meta):
                yield chunk
        else:
            async for chunk in self._handle_narrative(player_input):
                yield chunk

        world_changes = await self._world_reactor.process_tick(
            campaign_id=self.campaign_id,
            narrative_seconds=narrative_time,
            world_context=self._memory.build_context_window(self.campaign_id),
        )
        if world_changes:
            self._event_store.append(
                self.campaign_id, EventType.WORLD_TICK,
                {"text": world_changes}, 0, "world", [],
            )

    async def _handle_narrative(self, player_input: str) -> AsyncIterator[str]:
        memory_ctx = self._memory.build_context_window(self.campaign_id)
        system_prompt = self._narrator.build_system_prompt(
            tone_instructions=self.scenario_tone,
            memory_context=memory_ctx,
            language=self.language,
        )
        full_response = ""
        async for chunk in self._narrator.stream_narrative(player_input, system_prompt, self._history):
            full_response += chunk
            yield chunk

        self._history.append({"role": "user", "content": player_input})
        self._history.append({"role": "assistant", "content": full_response})
        self._event_store.append(
            self.campaign_id, EventType.NARRATOR_RESPONSE,
            {"text": full_response}, 0, "current", [],
        )
        await self._journal.evaluate_and_log(self.campaign_id, full_response)

    async def _handle_combat(self, player_input: str, meta: dict) -> AsyncIterator[str]:
        griefing = await self._combat.anti_griefing_check(player_input)
        if griefing.rejected:
            yield f"[The narrator shakes their head] {griefing.reason}"
            return

        npc_power = 5
        evaluation = await self._combat.evaluate_action(player_input, "enemy", npc_power)
        outcome = self._combat.roll_outcome(evaluation.final_quality, npc_power)

        self._event_store.append(
            self.campaign_id, EventType.COMBAT_RESULT,
            {"outcome": outcome, "quality": evaluation.final_quality}, 0, "current", [],
        )
        yield f"[{outcome}] "
        async for chunk in self._handle_narrative(player_input):
            yield chunk
```

**Step 3: Run tests**

```bash
pytest tests/services/test_game_session.py -v
```

Expected: 1 passed

**Step 4: Wire SSE into routes_game.py**

```python
# backend/app/api/routes_game.py (updated)
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.services.game_session import GameSession
from app.engines.narrator_engine import NarratorEngine
from app.engines.memory_engine import MemoryEngine
from app.engines.world_reactor import WorldReactor
from app.engines.journal_engine import JournalEngine
from app.engines.combat_engine import CombatEngine
from app.engines.llm_router import LLMRouter, LLMConfig
from app.db.event_store import EventStore

router = APIRouter()

_event_store = EventStore()
_llm = LLMRouter(LLMConfig())
_narrator = NarratorEngine(llm=_llm)
_memory = MemoryEngine(event_store=_event_store, llm=_llm)
_world_reactor = WorldReactor(llm=_llm)
_journal = JournalEngine(llm=_llm)
_combat = CombatEngine(llm=_llm)

_sessions: dict[str, GameSession] = {}


class PlayerActionRequest(BaseModel):
    campaign_id: str
    scenario_tone: str = ""
    language: str = "en"
    action: str


@router.post("/action")
async def player_action(req: PlayerActionRequest):
    if req.campaign_id not in _sessions:
        _sessions[req.campaign_id] = GameSession(
            campaign_id=req.campaign_id,
            scenario_tone=req.scenario_tone,
            language=req.language,
            narrator=_narrator,
            memory=_memory,
            world_reactor=_world_reactor,
            journal=_journal,
            event_store=_event_store,
            combat_engine=_combat,
        )

    session = _sessions[req.campaign_id]

    async def event_stream():
        async for chunk in session.process_action(req.action):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Step 5: Commit**

```bash
git add backend/app/services/game_session.py backend/app/api/routes_game.py backend/tests/services/
git commit -m "feat: wire all engines into GameSession with SSE streaming game loop"
```

---

## Phase 9 — Frontend

### Task 9.1: Frontend Store & API Client

**Files:**
- Create: `frontend/src/store.js`
- Create: `frontend/src/api.js`

**Step 1: Create Zustand store**

```js
// frontend/src/store.js
import { create } from 'zustand'

export const useGameStore = create((set, get) => ({
  // Scenario
  scenarios: [],
  activeScenario: null,
  activeCampaignId: null,

  // Narrative
  messages: [],
  isStreaming: false,

  // Journal
  journal: [],

  // Settings
  llmProvider: 'deepseek',
  llmModel: 'deepseek-chat',
  temperature: 0.8,
  maxTokens: 2000,

  setScenarios: (scenarios) => set({ scenarios }),
  setActiveScenario: (scenario) => set({ activeScenario: scenario }),
  setActiveCampaignId: (id) => set({ activeCampaignId: id }),
  appendMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  appendToLastMessage: (chunk) => set((s) => {
    const messages = [...s.messages]
    if (messages.length && messages[messages.length - 1].role === 'assistant') {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content: messages[messages.length - 1].content + chunk,
      }
    } else {
      messages.push({ role: 'assistant', content: chunk })
    }
    return { messages }
  }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  addJournalEntry: (entry) => set((s) => ({ journal: [...s.journal, entry] })),
  updateSettings: (settings) => set(settings),
}))
```

**Step 2: Create API client**

```js
// frontend/src/api.js
const BASE = 'http://localhost:8000/api'

export async function fetchScenarios() {
  const r = await fetch(`${BASE}/scenarios/`)
  return r.json()
}

export async function createScenario(data) {
  const r = await fetch(`${BASE}/scenarios/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return r.json()
}

export async function addStoryCard(scenarioId, data) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/story-cards`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return r.json()
}

export function streamAction({ campaignId, scenarioTone, language, action, onChunk, onDone }) {
  fetch(`${BASE}/game/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      campaign_id: campaignId,
      scenario_tone: scenarioTone,
      language,
      action,
    }),
  }).then(async (res) => {
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value)
      const lines = text.split('\n').filter((l) => l.startsWith('data: '))
      for (const line of lines) {
        const data = line.slice(6)
        if (data === '[DONE]') { onDone?.(); return }
        onChunk(data)
      }
    }
  })
}
```

**Step 3: Commit**

```bash
git add frontend/src/store.js frontend/src/api.js
git commit -m "feat: add Zustand store and API client with SSE streaming support"
```

---

### Task 9.2: GameCanvas Component

**Files:**
- Create: `frontend/src/components/GameCanvas.jsx`
- Create: `frontend/src/components/ActionInput.jsx`

**Step 1: Implement GameCanvas**

```jsx
// frontend/src/components/GameCanvas.jsx
import { useEffect, useRef } from 'react'
import { useGameStore } from '../store'
import { streamAction } from '../api'
import ActionInput from './ActionInput'
import ReactMarkdown from 'react-markdown'

export default function GameCanvas() {
  const { messages, isStreaming, appendToLastMessage, appendMessage, setStreaming,
          activeCampaignId, activeScenario } = useGameStore()
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleAction = (action) => {
    appendMessage({ role: 'user', content: action })
    setStreaming(true)
    streamAction({
      campaignId: activeCampaignId,
      scenarioTone: activeScenario?.tone_instructions ?? '',
      language: activeScenario?.language ?? 'en',
      action,
      onChunk: appendToLastMessage,
      onDone: () => setStreaming(false),
    })
  }

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100">
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={msg.role === 'user' ? 'text-right' : 'text-left'}>
            {msg.role === 'user' ? (
              <span className="inline-block bg-indigo-900 text-indigo-100 px-4 py-2 rounded-lg max-w-xl">
                {msg.content}
              </span>
            ) : (
              <div className="prose prose-invert max-w-2xl">
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <ActionInput onSubmit={handleAction} disabled={isStreaming} />
    </div>
  )
}
```

**Step 2: Implement ActionInput**

```jsx
// frontend/src/components/ActionInput.jsx
import { useState } from 'react'
import { Send } from 'lucide-react'

const ACTION_TYPES = ['DO', 'SAY', 'CONTINUE', 'META']

export default function ActionInput({ onSubmit, disabled }) {
  const [text, setText] = useState('')
  const [type, setType] = useState('DO')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!text.trim() || disabled) return
    onSubmit(`[${type}] ${text}`)
    setText('')
  }

  return (
    <form onSubmit={handleSubmit} className="border-t border-gray-800 p-4 bg-gray-900">
      <div className="flex gap-2 mb-2">
        {ACTION_TYPES.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors
              ${type === t ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled}
          placeholder={disabled ? 'Narrating...' : 'What do you do?'}
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-gray-100
                     placeholder-gray-500 focus:outline-none focus:border-indigo-500"
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg"
        >
          <Send size={18} />
        </button>
      </div>
    </form>
  )
}
```

**Step 3: Commit**

```bash
git add frontend/src/components/
git commit -m "feat: add GameCanvas with SSE streaming and action type selector"
```

---

### Task 9.3: ScenarioBuilder Component

**Files:**
- Create: `frontend/src/components/ScenarioBuilder.jsx`

**Step 1: Implement ScenarioBuilder**

```jsx
// frontend/src/components/ScenarioBuilder.jsx
import { useState } from 'react'
import { createScenario, addStoryCard } from '../api'
import { useGameStore } from '../store'

export default function ScenarioBuilder({ onCreated }) {
  const [form, setForm] = useState({
    title: '', description: '', tone_instructions: '',
    opening_narrative: '', language: 'en', lore_text: '',
  })
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    const scenario = await createScenario(form)
    setLoading(false)
    onCreated?.(scenario)
  }

  const field = (key, label, multiline = false, placeholder = '') => (
    <div>
      <label className="block text-sm font-medium text-gray-400 mb-1">{label}</label>
      {multiline ? (
        <textarea
          value={form[key]}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
          placeholder={placeholder}
          rows={4}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                     placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none"
        />
      ) : (
        <input
          value={form[key]}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
          placeholder={placeholder}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                     placeholder-gray-500 focus:outline-none focus:border-indigo-500"
        />
      )}
    </div>
  )

  return (
    <div className="max-w-2xl mx-auto p-6 bg-gray-900 rounded-xl">
      <h2 className="text-xl font-bold text-white mb-6">Create Scenario</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        {field('title', 'World Title', false, 'The Shattered Realm')}
        {field('description', 'Description', true, 'A brief description of your world...')}
        {field('tone_instructions', 'Tone & Style Instructions', true,
          'Dark and gritty. High mortality. NPCs have their own agendas...')}
        {field('opening_narrative', 'Opening Narrative', true,
          'The scene where the story begins...')}
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">Language</label>
          <select
            value={form.language}
            onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100"
          >
            <option value="en">English</option>
            <option value="pt-br">Português (BR)</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-400 mb-1">
            World Lore (optional — AI will extract entities automatically)
          </label>
          <textarea
            value={form.lore_text}
            onChange={(e) => setForm((f) => ({ ...f, lore_text: e.target.value }))}
            placeholder="Paste your world bible here. The AI will extract NPCs, locations, and factions automatically..."
            rows={8}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100
                       placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !form.title}
          className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white
                     font-medium py-2 rounded-lg transition-colors"
        >
          {loading ? 'Creating...' : 'Create Scenario'}
        </button>
      </form>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/ScenarioBuilder.jsx
git commit -m "feat: add ScenarioBuilder with hybrid form and lore extraction field"
```

---

### Task 9.4: App Router & Home

**Files:**
- Create: `frontend/src/App.jsx`
- Modify: `frontend/src/main.jsx`

**Step 1: Implement App with routing**

```jsx
// frontend/src/App.jsx
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import GameCanvas from './components/GameCanvas'
import ScenarioBuilder from './components/ScenarioBuilder'
import { useGameStore } from './store'
import { useEffect, useState } from 'react'
import { fetchScenarios } from './api'
import { v4 as uuidv4 } from 'crypto'

function Home() {
  const { scenarios, setScenarios, setActiveScenario, setActiveCampaignId } = useGameStore()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchScenarios().then((s) => { setScenarios(s); setLoading(false) })
  }, [])

  const startCampaign = (scenario) => {
    setActiveScenario(scenario)
    setActiveCampaignId(uuidv4())
    window.location.href = '/play'
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold text-white mb-2">Project Lunar</h1>
        <p className="text-gray-400 mb-8">AI-powered RPG storytelling engine</p>
        <div className="flex gap-4 mb-8">
          <Link to="/create" className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg">
            + New Scenario
          </Link>
        </div>
        {loading ? (
          <p className="text-gray-500">Loading scenarios...</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {scenarios.map((s) => (
              <div key={s.id} className="bg-gray-900 rounded-xl p-5 border border-gray-800 hover:border-indigo-700 transition-colors">
                <h3 className="text-lg font-semibold text-white mb-1">{s.title}</h3>
                <p className="text-gray-400 text-sm mb-4 line-clamp-2">{s.description}</p>
                <button
                  onClick={() => startCampaign(s)}
                  className="text-indigo-400 hover:text-indigo-300 text-sm font-medium"
                >
                  Play →
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/create" element={
          <div className="min-h-screen bg-gray-950 p-8">
            <ScenarioBuilder onCreated={() => window.location.href = '/'} />
          </div>
        } />
        <Route path="/play" element={<GameCanvas />} />
      </Routes>
    </BrowserRouter>
  )
}
```

**Step 2: Update main.jsx**

```jsx
// frontend/src/main.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

**Step 3: Commit**

```bash
git add frontend/src/App.jsx frontend/src/main.jsx
git commit -m "feat: add app router with home, scenario builder, and game canvas routes"
```

---

## Phase 10 — Integration & Full Test Suite

### Task 10.1: Run Full Test Suite

**Step 1: Run all backend tests**

```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

Expected: All tests pass, coverage > 70%

**Step 2: Start full stack and smoke test**

```bash
# Terminal 1
docker-compose up -d neo4j

# Terminal 2
cd backend && venv/Scripts/activate && uvicorn app.main:app --reload --port 8000

# Terminal 3
cd frontend && npm run dev
```

Open http://localhost:5173 — home screen should load.

**Step 3: Create a test scenario via UI**
1. Click "New Scenario"
2. Fill in title and tone
3. Paste lore text
4. Click Create
5. Click Play
6. Type an action and verify streaming works

**Step 4: Final commit**

```bash
git add .
git commit -m "chore: verify full stack integration and smoke test"
```

---

## Appendix: Running Tests by Module

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/engines/test_combat_engine.py -v
pytest tests/db/ -v
pytest tests/api/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

## Appendix: Adding a New LLM Provider

1. Add key to `.env` and `.env.example`
2. Add new value to `LLMProvider` enum in `llm_router.py`
3. Update `_build_model_string` if needed
4. Add to `LLMConfig` fallback options
5. Test via `/api/health` and a manual action
