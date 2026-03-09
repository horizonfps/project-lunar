"""Tests for GraphitiEngine wrapper (mocked — no Neo4j required)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_graphiti_instance():
    """Create a mock Graphiti instance with async methods."""
    mock = AsyncMock()
    mock.build_indices_and_constraints = AsyncMock()
    mock.add_episode = AsyncMock()
    mock.search = AsyncMock(return_value=[])
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def engine(mock_graphiti_instance):
    """Create a GraphitiEngine with an injected mock."""
    with patch("app.engines.graphiti_engine.Graphiti", return_value=mock_graphiti_instance):
        from app.engines.graphiti_engine import GraphitiEngine

        eng = GraphitiEngine("bolt://localhost:7687", "neo4j", "password")
        eng._graphiti = mock_graphiti_instance
        return eng


@pytest.mark.asyncio
async def test_initialize_builds_indices(engine, mock_graphiti_instance):
    """Verify build_indices_and_constraints is called on initialize."""
    await engine.initialize()
    mock_graphiti_instance.build_indices_and_constraints.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_episode_calls_add_episode(engine, mock_graphiti_instance):
    """Verify add_episode is called with correct group_id, episode_body, source_description."""
    await engine.ingest_episode(
        campaign_id="camp-1",
        text="The dragon attacked the village.",
        description="combat_narrative",
    )
    mock_graphiti_instance.add_episode.assert_awaited_once()
    call_kwargs = mock_graphiti_instance.add_episode.call_args.kwargs
    assert call_kwargs["group_id"] == "camp-1"
    assert call_kwargs["episode_body"] == "The dragon attacked the village."
    assert call_kwargs["source_description"] == "combat_narrative"


@pytest.mark.asyncio
async def test_search_returns_facts(engine, mock_graphiti_instance):
    """Mock search returning edge objects with .fact attribute, verify dict output."""
    edge1 = MagicMock()
    edge1.fact = "Dragons are vulnerable to ice magic."
    edge1.valid_at = None
    edge1.invalid_at = None

    edge2 = MagicMock()
    edge2.fact = "The village has a protective ward."
    edge2.valid_at = None
    edge2.invalid_at = None

    mock_graphiti_instance.search = AsyncMock(return_value=[edge1, edge2])

    results = await engine.search(campaign_id="camp-1", query="dragon weakness")
    assert len(results) == 2
    assert results[0]["fact"] == "Dragons are vulnerable to ice magic."
    assert results[1]["fact"] == "The village has a protective ward."


@pytest.mark.asyncio
async def test_ingest_episode_skips_empty_text(engine, mock_graphiti_instance):
    """Verify add_episode is NOT called for empty text."""
    await engine.ingest_episode(campaign_id="camp-1", text="")
    await engine.ingest_episode(campaign_id="camp-1", text="   ")
    mock_graphiti_instance.add_episode.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_closes_graphiti(engine, mock_graphiti_instance):
    """Verify close is called on the underlying Graphiti instance."""
    await engine.close()
    mock_graphiti_instance.close.assert_awaited_once()
