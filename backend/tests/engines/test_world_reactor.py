import pytest
from unittest.mock import AsyncMock
from app.engines.world_reactor import WorldReactor, TickType


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Minor shifts in NPC mood across the region.")
    return llm


@pytest.fixture
def reactor(mock_llm):
    return WorldReactor(llm=mock_llm)


def test_classify_tick_micro(reactor):
    assert reactor.classify_tick(300) == TickType.MICRO       # 5 minutes


def test_classify_tick_minor(reactor):
    assert reactor.classify_tick(7200) == TickType.MINOR      # 2 hours


def test_classify_tick_moderate(reactor):
    assert reactor.classify_tick(172800) == TickType.MODERATE  # 2 days


def test_classify_tick_major(reactor):
    assert reactor.classify_tick(864000) == TickType.MAJOR    # 10 days


def test_classify_tick_heavy(reactor):
    assert reactor.classify_tick(2592000) == TickType.HEAVY   # 30 days


@pytest.mark.asyncio
async def test_micro_tick_returns_empty(reactor):
    changes = await reactor.process_tick(
        campaign_id="c1",
        narrative_seconds=60,
        world_context="A quiet village.",
    )
    assert changes == ""


@pytest.mark.asyncio
async def test_minor_tick_returns_world_changes(reactor, mock_llm):
    mock_llm.complete = AsyncMock(return_value="A merchant arrives from the capital with news.")
    changes = await reactor.process_tick(
        campaign_id="c1",
        narrative_seconds=7200,
        world_context="The king is ill. The warlord eyes the throne.",
    )
    assert isinstance(changes, str)
    assert len(changes) > 0
