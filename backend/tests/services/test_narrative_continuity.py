from unittest.mock import MagicMock

from app.services.game_session import GameSession


def test_open_scene_overlap_widens_with_the_provider_window():
    assert GameSession._open_scene_overlap_batches(64_000) == 1
    assert GameSession._open_scene_overlap_batches(200_000) == 8
    assert GameSession._open_scene_overlap_batches(1_000_000) == 20


def test_context_window_falls_back_when_provider_returns_no_int():
    s = GameSession(
        campaign_id="c1", scenario_tone="", language="en",
        narrator=MagicMock(), memory=MagicMock(), world_reactor=MagicMock(),
        journal=MagicMock(), event_store=MagicMock(),
    )
    assert s._get_context_window() == 64_000