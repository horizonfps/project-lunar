"""Wrapper around graphiti-core for temporal knowledge graph ingestion and search."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

try:
    from graphiti_core import Graphiti
except ImportError:
    Graphiti = None

logger = logging.getLogger(__name__)


class GraphitiEngine:
    """Thin wrapper around Graphiti for RPG narrative episode ingestion."""

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        if Graphiti is None:
            raise ImportError("graphiti-core is not installed")
        self._graphiti = Graphiti(neo4j_uri, neo4j_user, neo4j_password)

    async def initialize(self):
        """Build Graphiti indices and constraints. Call once on startup."""
        await self._graphiti.build_indices_and_constraints()

    async def ingest_episode(
        self,
        campaign_id: str,
        text: str,
        description: str = "narrative",
        reference_time: datetime | None = None,
    ):
        """Ingest a narrative text chunk as a Graphiti episode."""
        if not text or not text.strip():
            return

        ref_time = reference_time or datetime.now(timezone.utc)
        try:
            await self._graphiti.add_episode(
                name=f"{campaign_id}_{ref_time.isoformat()}",
                episode_body=text,
                source_description=description,
                reference_time=ref_time,
                group_id=campaign_id,
            )
        except Exception:
            logger.exception("Failed to ingest episode for campaign %s", campaign_id)

    async def search(self, campaign_id: str, query: str, limit: int = 10) -> list[dict]:
        """Search for temporal facts relevant to a query within a campaign."""
        try:
            edges = await self._graphiti.search(query, group_ids=[campaign_id], num_results=limit)
            return [
                {
                    "fact": edge.fact,
                    "valid_at": edge.valid_at.isoformat() if getattr(edge, "valid_at", None) else None,
                    "invalid_at": edge.invalid_at.isoformat() if getattr(edge, "invalid_at", None) else None,
                }
                for edge in edges
            ]
        except Exception:
            logger.exception("Graphiti search failed for campaign %s", campaign_id)
            return []

    async def close(self):
        """Close the Graphiti connection."""
        await self._graphiti.close()
