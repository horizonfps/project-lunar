import json
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
                    attributes_json: $attributes_json
                })
                """,
                node_id=node_id,
                node_type=node_type.value,
                name=name,
                campaign_id=self.campaign_id,
                attributes_json=json.dumps(attributes),
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
        # rel_type must be a valid Cypher identifier — sanitize to uppercase alphanumeric
        safe_rel_type = "".join(c for c in rel_type.upper() if c.isalnum() or c == "_")
        async with self._driver.session() as session:
            await session.run(
                f"""
                MATCH (a:WorldNode {{node_id: $source_id, campaign_id: $campaign_id}})
                MATCH (b:WorldNode {{node_id: $target_id, campaign_id: $campaign_id}})
                MERGE (a)-[r:{safe_rel_type}]->(b)
                SET r.strength = $strength, r.campaign_id = $campaign_id
                """,
                source_id=source_id,
                target_id=target_id,
                campaign_id=self.campaign_id,
                strength=strength,
            )
        return Relationship(source_id, target_id, rel_type, strength)

    async def get_npc_power(self, name: str) -> int:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (n:WorldNode {name: $name, campaign_id: $campaign_id, node_type: 'NPC'})
                RETURN n.attributes_json AS attrs
                LIMIT 1
                """,
                name=name,
                campaign_id=self.campaign_id,
            )
            record = await result.single()
            if not record:
                return 5
            attrs = json.loads(record["attrs"])
            return int(attrs.get("power_level", 5))

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
                    attributes=json.loads(b.get("attributes_json", "{}")),
                    campaign_id=b["campaign_id"],
                ))
            return nodes

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

    async def clear_campaign(self, campaign_id: str):
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:WorldNode {campaign_id: $campaign_id}) DETACH DELETE n",
                campaign_id=campaign_id,
            )

    async def close(self):
        await self._driver.close()
