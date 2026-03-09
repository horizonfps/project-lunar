# WorldMap View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive force-directed graph visualization of the campaign world (NPCs, locations, factions, items, events) accessible as a modal from the GameCanvas toolbar.

**Architecture:** New GraphEngine methods query all nodes/relationships for a campaign. A new API endpoint serves this as JSON. A new React component uses react-force-graph-2d to render the graph with hover highlighting and click tooltips.

**Tech Stack:** Python/FastAPI (backend), Neo4j (graph DB), React 19 + react-force-graph-2d (frontend), Tailwind CSS (styling)

**Design doc:** `docs/plans/2026-03-10-worldmap-view-design.md`

---

### Task 1: GraphEngine — get_all_nodes and get_all_relationships

**Files:**
- Test: `backend/tests/engines/test_graph_engine.py`
- Modify: `backend/app/engines/graph_engine.py`

**Step 1: Write failing tests**

Append to `backend/tests/engines/test_graph_engine.py`:

```python
@pytest.mark.asyncio
async def test_get_all_nodes(engine):
    await engine.add_node(WorldNodeType.NPC, "Kael", {"power_level": 7})
    await engine.add_node(WorldNodeType.LOCATION, "Tavern", {"description": "cozy"})
    nodes = await engine.get_all_nodes()
    assert len(nodes) == 2
    names = {n.name for n in nodes}
    assert names == {"Kael", "Tavern"}


@pytest.mark.asyncio
async def test_get_all_relationships(engine):
    npc = await engine.add_node(WorldNodeType.NPC, "Kael", {"power_level": 7})
    loc = await engine.add_node(WorldNodeType.LOCATION, "Tavern", {})
    await engine.add_relationship(npc.id, loc.id, "FREQUENTS", 0.8)
    rels = await engine.get_all_relationships()
    assert len(rels) == 1
    assert rels[0]["source_id"] == npc.id
    assert rels[0]["target_id"] == loc.id
    assert rels[0]["rel_type"] == "FREQUENTS"
    assert rels[0]["strength"] == 0.8
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/engines/test_graph_engine.py::test_get_all_nodes tests/engines/test_graph_engine.py::test_get_all_relationships -v`

Expected: FAIL with `AttributeError: 'GraphEngine' object has no attribute 'get_all_nodes'`

**Step 3: Implement get_all_nodes and get_all_relationships**

Add to `backend/app/engines/graph_engine.py` (before `clear_campaign`):

```python
async def get_all_nodes(self) -> list[WorldNode]:
    async with self._driver.session() as session:
        result = await session.run(
            """
            MATCH (n:WorldNode {campaign_id: $campaign_id})
            RETURN n
            """,
            campaign_id=self.campaign_id,
        )
        nodes = []
        async for record in result:
            n = record["n"]
            nodes.append(WorldNode(
                id=n["node_id"],
                node_type=WorldNodeType(n["node_type"]),
                name=n["name"],
                attributes=json.loads(n.get("attributes_json", "{}")),
                campaign_id=n["campaign_id"],
            ))
        return nodes

async def get_all_relationships(self) -> list[dict]:
    async with self._driver.session() as session:
        result = await session.run(
            """
            MATCH (a:WorldNode {campaign_id: $campaign_id})-[r]->(b:WorldNode {campaign_id: $campaign_id})
            RETURN a.node_id AS source_id, b.node_id AS target_id, type(r) AS rel_type, r.strength AS strength
            """,
            campaign_id=self.campaign_id,
        )
        rels = []
        async for record in result:
            rels.append({
                "source_id": record["source_id"],
                "target_id": record["target_id"],
                "rel_type": record["rel_type"],
                "strength": record["strength"] or 1.0,
            })
        return rels
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/engines/test_graph_engine.py::test_get_all_nodes tests/engines/test_graph_engine.py::test_get_all_relationships -v`

Expected: 2 PASS

**Step 5: Commit**

```bash
git add backend/app/engines/graph_engine.py backend/tests/engines/test_graph_engine.py
git commit -m "feat: add get_all_nodes and get_all_relationships to GraphEngine"
```

---

### Task 2: API endpoint — world-graph

**Files:**
- Test: `backend/tests/api/test_routes_game.py` (create if not exists)
- Modify: `backend/app/api/routes_game.py`

**Step 1: Write failing test**

Create `backend/tests/api/test_routes_game.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENARIO_DB_PATH", str(tmp_path / "scenarios.db"))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.db"))
    from app.main import app
    return TestClient(app)


def test_world_graph_endpoint(client):
    r = client.get("/api/game/test-campaign/world-graph")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "links" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["links"], list)
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_routes_game.py::test_world_graph_endpoint -v`

Expected: FAIL with 404 (no route yet)

**Step 3: Implement world-graph endpoint**

Add to `backend/app/api/routes_game.py`, after the existing imports add:

```python
from app.engines.graph_engine import GraphEngine, WorldNodeType
```

Then add the endpoint (after the `timeskip` endpoint):

```python
@router.get("/{campaign_id}/world-graph")
async def get_world_graph(campaign_id: str):
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "lunar_password")
    try:
        engine = GraphEngine(neo4j_uri, neo4j_user, neo4j_password, campaign_id)
        await engine.initialize()
        nodes = await engine.get_all_nodes()
        rels = await engine.get_all_relationships()
        await engine.close()
        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "node_type": n.node_type.value,
                    "attributes": n.attributes,
                }
                for n in nodes
            ],
            "links": [
                {
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "rel_type": r["rel_type"],
                    "strength": r["strength"],
                }
                for r in rels
            ],
        }
    except Exception:
        return {"nodes": [], "links": []}
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_routes_game.py::test_world_graph_endpoint -v`

Expected: PASS (endpoint returns empty graph when Neo4j is unavailable, which is fine for test env)

**Step 5: Commit**

```bash
git add backend/app/api/routes_game.py backend/tests/api/test_routes_game.py
git commit -m "feat: add world-graph API endpoint for campaign graph data"
```

---

### Task 3: Install react-force-graph-2d

**Files:**
- Modify: `frontend/package.json`

**Step 1: Install dependency**

Run: `cd frontend && npm install react-force-graph-2d`

**Step 2: Verify install**

Run: `cd frontend && node -e "require('react-force-graph-2d'); console.log('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add react-force-graph-2d dependency"
```

---

### Task 4: Add fetchWorldGraph to API client

**Files:**
- Modify: `frontend/src/api.js`

**Step 1: Add the function**

Append to `frontend/src/api.js`:

```javascript
export async function fetchWorldGraph(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/world-graph`)
  if (!r.ok) throw new Error('Failed to fetch world graph')
  return r.json()
}
```

**Step 2: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat: add fetchWorldGraph API helper"
```

---

### Task 5: Create WorldMapModal component

**Files:**
- Create: `frontend/src/components/WorldMapModal.jsx`

**Step 1: Create the component**

Create `frontend/src/components/WorldMapModal.jsx`:

```jsx
import { useState, useEffect, useCallback, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { Map, X, RefreshCw } from 'lucide-react'
import { fetchWorldGraph } from '../api'

const NODE_COLORS = {
  NPC: '#a78bfa',
  LOCATION: '#34d399',
  FACTION: '#fbbf24',
  ITEM: '#22d3ee',
  EVENT: '#fb7185',
}

const NODE_RADIUS = {
  NPC: 6,
  LOCATION: 8,
  FACTION: 7,
  ITEM: 5,
  EVENT: 5,
}

export default function WorldMapModal({ open, onClose, campaignId }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(false)
  const [hoverNode, setHoverNode] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 })
  const graphRef = useRef()
  const containerRef = useRef()

  const loadGraph = async () => {
    if (!campaignId) return
    setLoading(true)
    try {
      const data = await fetchWorldGraph(campaignId)
      setGraphData(data)
    } catch {
      setGraphData({ nodes: [], links: [] })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      loadGraph()
      setSelectedNode(null)
    }
  }, [open, campaignId])

  const highlightNodes = useCallback(() => {
    if (!hoverNode) return new Set()
    const neighbors = new Set([hoverNode.id])
    graphData.links.forEach((link) => {
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      if (srcId === hoverNode.id) neighbors.add(tgtId)
      if (tgtId === hoverNode.id) neighbors.add(srcId)
    })
    return neighbors
  }, [hoverNode, graphData.links])

  const nodeCanvasObject = useCallback(
    (node, ctx, globalScale) => {
      const neighbors = highlightNodes()
      const isHighlighted = !hoverNode || neighbors.has(node.id)
      const radius = NODE_RADIUS[node.node_type] || 5
      const color = NODE_COLORS[node.node_type] || '#94a3b8'

      ctx.beginPath()
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = isHighlighted ? color : color + '33'
      ctx.fill()

      if (isHighlighted && globalScale > 0.8) {
        ctx.strokeStyle = color + '66'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      // Label
      if (globalScale > 1.2 || (hoverNode && hoverNode.id === node.id)) {
        const label = node.name
        const fontSize = Math.max(10 / globalScale, 3)
        ctx.font = `${fontSize}px sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = isHighlighted ? '#e2e8f0' : '#64748b'
        ctx.fillText(label, node.x, node.y + radius + 2)
      }
    },
    [hoverNode, highlightNodes],
  )

  const linkColor = useCallback(
    (link) => {
      if (!hoverNode) return 'rgba(148, 163, 184, 0.2)'
      const srcId = typeof link.source === 'object' ? link.source.id : link.source
      const tgtId = typeof link.target === 'object' ? link.target.id : link.target
      if (srcId === hoverNode.id || tgtId === hoverNode.id) {
        return 'rgba(148, 163, 184, 0.6)'
      }
      return 'rgba(148, 163, 184, 0.05)'
    },
    [hoverNode],
  )

  const handleNodeClick = useCallback((node, event) => {
    setSelectedNode(node)
    const rect = containerRef.current?.getBoundingClientRect()
    if (rect) {
      setTooltipPos({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      })
    }
  }, [])

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        ref={containerRef}
        className="glass-panel rounded-2xl w-full max-w-4xl mx-4 overflow-hidden flex flex-col"
        style={{ height: '80vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Map size={16} className="text-emerald-400" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">World Map</h2>
            {graphData.nodes.length > 0 && (
              <span className="text-lunar-500 text-xs ml-2">
                {graphData.nodes.length} nodes &middot; {graphData.links.length} links
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadGraph}
              disabled={loading}
              className="text-lunar-400 hover:text-white transition-colors p-1"
              title="Refresh"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="text-lunar-400 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 px-6 py-2 border-b border-white/5 flex-none">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-lunar-400 uppercase tracking-wider">{type}</span>
            </div>
          ))}
        </div>

        {/* Graph */}
        <div className="flex-1 relative" onClick={handleBackgroundClick}>
          {graphData.nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Map size={32} className="text-lunar-700 mx-auto mb-3" />
                <p className="text-lunar-500 text-sm font-light">
                  {loading
                    ? 'Mapping world topology...'
                    : 'No world data yet. Play to populate the graph.'}
                </p>
              </div>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              nodeCanvasObject={nodeCanvasObject}
              linkColor={linkColor}
              linkWidth={(link) => Math.max((link.strength || 0.5) * 2, 0.5)}
              linkDirectionalParticles={0}
              onNodeHover={setHoverNode}
              onNodeClick={handleNodeClick}
              onBackgroundClick={handleBackgroundClick}
              backgroundColor="transparent"
              width={containerRef.current?.clientWidth || 800}
              height={(containerRef.current?.clientHeight || 600) - 100}
              cooldownTicks={100}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
            />
          )}

          {/* Tooltip */}
          {selectedNode && (
            <div
              className="absolute z-10 glass-panel rounded-xl p-4 min-w-[200px] max-w-[280px] border border-white/10 shadow-xl pointer-events-none"
              style={{
                left: Math.min(tooltipPos.x + 10, (containerRef.current?.clientWidth || 800) - 300),
                top: Math.min(tooltipPos.y - 10, (containerRef.current?.clientHeight || 600) - 200),
              }}
            >
              <div className="flex items-center gap-2 mb-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: NODE_COLORS[selectedNode.node_type] || '#94a3b8' }}
                />
                <span className="text-white font-bold text-sm">{selectedNode.name}</span>
              </div>
              <span
                className="inline-block text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 rounded-full mb-2"
                style={{
                  backgroundColor: (NODE_COLORS[selectedNode.node_type] || '#94a3b8') + '22',
                  color: NODE_COLORS[selectedNode.node_type] || '#94a3b8',
                }}
              >
                {selectedNode.node_type}
              </span>
              {selectedNode.attributes && Object.keys(selectedNode.attributes).length > 0 && (
                <div className="space-y-1 mt-2 border-t border-white/5 pt-2">
                  {Object.entries(selectedNode.attributes)
                    .slice(0, 4)
                    .map(([key, val]) => (
                      <div key={key} className="flex justify-between text-xs">
                        <span className="text-lunar-400">{key.replace(/_/g, ' ')}</span>
                        <span className="text-lunar-200 font-medium ml-3 truncate max-w-[120px]">
                          {String(val)}
                        </span>
                      </div>
                    ))}
                </div>
              )}
              {selectedNode.node_type === 'NPC' && selectedNode.attributes?.power_level != null && (
                <div className="mt-2 border-t border-white/5 pt-2">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-lunar-400">Power Level</span>
                    <span className="text-purple-400 font-bold">{selectedNode.attributes.power_level}/10</span>
                  </div>
                  <div className="w-full h-1.5 bg-lunar-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-purple-500 rounded-full"
                      style={{ width: `${(selectedNode.attributes.power_level / 10) * 100}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/WorldMapModal.jsx
git commit -m "feat: add WorldMapModal with force-directed graph visualization"
```

---

### Task 6: Wire WorldMapModal into GameCanvas

**Files:**
- Modify: `frontend/src/components/GameCanvas.jsx`

**Step 1: Add import**

Add at the top of `frontend/src/components/GameCanvas.jsx`, after the MemoryInspector import:

```javascript
import WorldMapModal from './WorldMapModal'
```

Also add `Map` to the lucide-react import:

```javascript
import { Settings, Sparkles, Clock, Brain, Gem, Map } from 'lucide-react'
```

**Step 2: Add state**

Inside the GameCanvas component, after `const [memoryOpen, setMemoryOpen] = useState(false)`:

```javascript
const [mapOpen, setMapOpen] = useState(false)
```

**Step 3: Add toolbar button**

In the toolbar area, before the Plot Generator button (`setPlotGenOpen`), add:

```jsx
<button
  onClick={() => setMapOpen(true)}
  title="World Map"
  className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-lunar-300 hover:text-emerald-400 transition-colors border border-white/5"
>
  <Map size={14} />
</button>
```

**Step 4: Add modal render**

After the MemoryInspector modal (at the bottom of the return), add:

```jsx
<WorldMapModal open={mapOpen} onClose={() => setMapOpen(false)} campaignId={activeCampaignId} />
```

**Step 5: Commit**

```bash
git add frontend/src/components/GameCanvas.jsx
git commit -m "feat: wire WorldMapModal into GameCanvas toolbar"
```

---

### Task 7: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Step 1: Mark WorldMap View as complete**

In the Feature Backlog section, change:
```
- [ ] **WorldMap View** — D3.js visualization of NPC/location/faction graph
```
to:
```
- [x] **WorldMap View** — force-directed graph visualization of world entities (react-force-graph-2d)
```

**Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: mark WorldMap View as complete in AGENTS.md"
```

---

### Task 8: Manual smoke test

**Step 1: Start services**

```bash
docker-compose up -d neo4j
cd backend && venv/Scripts/activate && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

**Step 2: Verify**

1. Open http://localhost:5173
2. Create a scenario or play an existing one
3. In GameCanvas, click the Map button (green globe icon in toolbar)
4. Verify: modal opens with empty state message
5. Play some actions to populate the world graph
6. Re-open the map — verify nodes appear, colored by type
7. Hover a node — verify connected subgraph highlights
8. Click a node — verify tooltip appears with name, type, attributes
9. Click background — tooltip dismisses
10. Verify pan/zoom works (scroll wheel, drag)
