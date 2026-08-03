import asyncio

import pytest
from unittest.mock import MagicMock

import app.services.game_session as gs
from app.services.game_session import GameSession, _narrator_audit_enabled, _audit_timeout_s


def _make_session():
    return GameSession(
        campaign_id="c1",
        scenario_tone="grim",
        language="en",
        narrator=MagicMock(),
        memory=MagicMock(),
        world_reactor=MagicMock(),
        journal=MagicMock(),
        event_store=MagicMock(),
    )


def test_flag_default_on(monkeypatch):
    monkeypatch.delenv("LUNAR_FEATURE_NARRATOR_AUDIT", raising=False)
    assert _narrator_audit_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "OFF"])
def test_flag_off_values(monkeypatch, val):
    monkeypatch.setenv("LUNAR_FEATURE_NARRATOR_AUDIT", val)
    assert _narrator_audit_enabled() is False


@pytest.mark.parametrize("bad", ["", "abc", "90s", "inf", "nan", "-5", "0"])
def test_audit_timeout_bad_values_degrade_to_default(monkeypatch, bad):
    # A misconfigured timeout must never crash import; it degrades to the default.
    monkeypatch.setenv("LUNAR_AUDIT_TIMEOUT_S", bad)
    assert _audit_timeout_s() == 210.0


def test_audit_timeout_valid_value(monkeypatch):
    monkeypatch.setenv("LUNAR_AUDIT_TIMEOUT_S", "30")
    assert _audit_timeout_s() == 30.0


@pytest.mark.asyncio
async def test_audit_narrative_returns_corrected_prose():
    s = _make_session()

    class _Auditor:
        async def audit(self, prose, player_input, language="en", tone_instructions="", max_tokens=2000, **kwargs):
            return "corrected prose", {"prose_rewritten": True, "corrections": [{"rule_violated": "form"}]}

    s._auditor = _Auditor()
    out = await s._audit_narrative("raw prose", "do a thing")
    assert out == "corrected prose"


@pytest.mark.asyncio
async def test_audit_narrative_falls_back_on_timeout(monkeypatch):
    s = _make_session()
    monkeypatch.setattr(gs, "_AUDIT_TIMEOUT_S", 0.01)

    class _SlowAuditor:
        async def audit(self, *a, **k):
            await asyncio.sleep(0.2)
            return "should never surface", {}

    s._auditor = _SlowAuditor()
    out = await s._audit_narrative("original prose", "x")
    assert out == "original prose"


@pytest.mark.asyncio
async def test_audit_narrative_falls_back_on_error():
    s = _make_session()

    class _BoomAuditor:
        async def audit(self, *a, **k):
            raise RuntimeError("boom")

    s._auditor = _BoomAuditor()
    out = await s._audit_narrative("original prose", "x")
    assert out == "original prose"
