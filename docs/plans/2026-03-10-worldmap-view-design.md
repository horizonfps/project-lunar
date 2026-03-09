# WorldMap View — Design Document

> Date: 2026-03-10
> Status: Approved

## Overview

Interactive force-directed graph visualization of the campaign's world entities (NPCs, locations, factions, items, events) and their relationships. Accessed as a modal from the GameCanvas toolbar, consistent with existing UI patterns.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| UI placement | Toolbar modal in GameCanvas | Consistent with NPC Inspector, Memory Crystals, etc. |
| Visualization lib | react-force-graph-2d | D3-force under the hood, React wrapper, less boilerplate |
| Data source | Neo4j via new API endpoint | GraphEngine already holds canonical world graph |
| Interactivity | Pan/zoom + click details + hover highlight | Exploration-focused, not editing |
| Detail display | Floating tooltip popup | Lightweight, keeps map front-and-center |

## Backend

### New GraphEngine Methods

```python
# graph_engine.py
async def get_all_nodes(self) -> list[WorldNode]:
    """Return all WorldNodes for the current campaign."""

async def get_all_relationships(self) -> list[dict]:
    """Return all relationships for the current campaign.
    Returns: [{ source_id, target_id, rel_type, strength }]
    """
```

### New API Endpoint

```
GET /api/game/{campaign_id}/world-graph
```

Response shape (matches react-force-graph input):
```json
{
  "nodes": [
    { "id": "uuid", "name": "Kael", "node_type": "NPC", "attributes": {...} }
  ],
  "links": [
    { "source": "uuid-a", "target": "uuid-b", "rel_type": "ALLIED_WITH", "strength": 0.8 }
  ]
}
```

Requires a live Neo4j connection. Returns empty graph if Neo4j is unreachable.

## Frontend

### New Dependency

```
npm install react-force-graph-2d
```

### New Component: WorldMapModal.jsx

- Opens from a new toolbar button (Map icon from lucide-react)
- Full-width modal with dark background matching lunar theme
- Force-directed graph rendered with `ForceGraph2D`
- Node rendering: colored circles by type + name label
  - NPC → purple (#a78bfa)
  - LOCATION → emerald (#34d399)
  - FACTION → amber (#fbbf24)
  - ITEM → cyan (#22d3ee)
  - EVENT → rose (#fb7185)
- Relationship lines: semi-transparent, labeled with rel_type
- **Hover**: highlight hovered node + its direct neighbors, dim everything else
- **Click**: show floating tooltip card with name, type, key attributes, power level (NPCs)
- **Pan/zoom**: built-in from react-force-graph-2d

### Tooltip Card

Glass-panel styled card positioned near the clicked node:
- Node name (bold, white)
- Type badge (colored)
- Key attributes (2-3 lines max)
- Power level bar (NPCs only)
- Click away to dismiss

### Store Changes

None required. The world graph data is fetched on-demand when the modal opens and held in component-local state.

## Data Flow

```
User clicks Map button
  → WorldMapModal opens
  → fetch GET /api/game/{campaignId}/world-graph
  → Transform response into react-force-graph format
  → ForceGraph2D renders nodes + links
  → User hovers node → highlight subgraph
  → User clicks node → tooltip popup with details
```

## Testing

### Backend
- `test_get_all_nodes` — returns nodes filtered by campaign_id
- `test_get_all_relationships` — returns relationships for campaign nodes
- `test_world_graph_endpoint` — API returns correct shape

### Frontend
- Manual verification: open map, verify nodes render, hover/click interactions work
