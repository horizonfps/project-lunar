import pytest
import asyncio
from app.engines.graph_engine import GraphEngine, WorldNode, WorldNodeType, Relationship

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "lunar_password"
TEST_CAMPAIGN = "test-graph-engine-campaign"


@pytest.fixture
async def engine():
    eng = GraphEngine(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        campaign_id=TEST_CAMPAIGN,
    )
    await eng.initialize()
    yield eng
    await eng.clear_campaign(TEST_CAMPAIGN)
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
    assert node.node_type == WorldNodeType.NPC


@pytest.mark.asyncio
async def test_add_location_node(engine):
    node = await engine.add_node(
        node_type=WorldNodeType.LOCATION,
        name="Iron Fortress",
        attributes={"description": "A dark stronghold"},
    )
    assert node.name == "Iron Fortress"


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
    assert rel.source_id == npc.id
    assert rel.target_id == loc.id
    assert rel.rel_type == "CONTROLS"


@pytest.mark.asyncio
async def test_get_npc_power_level(engine):
    await engine.add_node(WorldNodeType.NPC, "WeakGoblin", {"power_level": 2})
    power = await engine.get_npc_power(name="WeakGoblin")
    assert power == 2


@pytest.mark.asyncio
async def test_get_npc_power_default_for_unknown(engine):
    power = await engine.get_npc_power(name="NonExistentNPC")
    assert power == 5  # default mid-level


@pytest.mark.asyncio
async def test_query_neighbors(engine):
    npc = await engine.add_node(WorldNodeType.NPC, "King", {"power_level": 8})
    loc = await engine.add_node(WorldNodeType.LOCATION, "Throne Room", {})
    await engine.add_relationship(npc.id, loc.id, "RESIDES_IN", 1.0)
    neighbors = await engine.get_neighbors(npc.id)
    assert any(n.name == "Throne Room" for n in neighbors)


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
