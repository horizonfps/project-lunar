import json
import logging

import pytest

from app.engines.auditor_engine import AuditorEngine


class _FakeLLM:
    """Records the last call and returns a scripted raw string (or raises)."""

    def __init__(self, reply=None, raises=None):
        self._reply = reply
        self._raises = raises
        self.last_messages = None
        self.last_max_tokens = None

    async def complete(self, messages, max_tokens=None, **kwargs):
        self.last_messages = messages
        self.last_max_tokens = max_tokens
        if self._raises is not None:
            raise self._raises
        return self._reply


def _reply(**fields):
    return json.dumps(fields)


@pytest.mark.asyncio
async def test_clean_verdict_returns_original():
    llm = _FakeLLM(_reply(verdict="clean", corrections=[]))
    a = AuditorEngine(llm)
    prose = "The gate opens."
    out, report = await a.audit(prose, "open the gate", language="en")
    assert out == prose
    assert report["verdict"] == "clean"
    assert report["prose_rewritten"] is False


@pytest.mark.asyncio
async def test_corrected_verdict_applies_rewrite():
    fixed = "You push. The gate opens."
    llm = _FakeLLM(_reply(
        verdict="corrected",
        corrections=[{"rule_violated": "agency", "reasoning": "rendered input"}],
        final_prose=fixed,
    ))
    a = AuditorEngine(llm)
    out, report = await a.audit("The gate opens.", "push the gate", language="en")
    assert out == fixed
    assert report["prose_rewritten"] is True
    assert len(report["corrections"]) == 1


@pytest.mark.asyncio
async def test_parse_failure_releases_original():
    llm = _FakeLLM("not json at all, just prose")
    a = AuditorEngine(llm)
    prose = "The gate opens."
    out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["error"] == "parse_failed"


@pytest.mark.asyncio
async def test_llm_exception_releases_original():
    llm = _FakeLLM(raises=RuntimeError("boom"))
    a = AuditorEngine(llm)
    prose = "The gate opens."
    out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["error"] == "llm_call_failed"


@pytest.mark.asyncio
async def test_empty_prose_short_circuits():
    llm = _FakeLLM(_reply(verdict="corrected", final_prose="something"))
    a = AuditorEngine(llm)
    out, report = await a.audit("   ", "x", language="en")
    assert out == "   "
    assert llm.last_messages is None  # no LLM call made


@pytest.mark.asyncio
async def test_marker_guard_rejects_rewrite_that_drops_item_tag():
    # Original carries a load-bearing inventory tag; rewrite loses it -> reject.
    prose = "You find a blade. [ITEM_ADD:Iron Blade|weapon|found in the ruins]"
    llm = _FakeLLM(_reply(
        verdict="corrected",
        final_prose="You find a blade in the ruins.",  # tag gone
        corrections=[{"rule_violated": "form", "reasoning": "x"}],
    ))
    a = AuditorEngine(llm)
    out, report = await a.audit(prose, "search", language="en")
    assert out == prose  # original preserved
    assert report["prose_rewritten"] is False
    assert report.get("marker_guard_rejected") is True


@pytest.mark.asyncio
async def test_marker_guard_accepts_rewrite_that_keeps_item_tag():
    prose = "You find, at last, a blade. [ITEM_ADD:Iron Blade|weapon|found]"
    fixed = "You find a blade. [ITEM_ADD:Iron Blade|weapon|found]"
    llm = _FakeLLM(_reply(verdict="corrected", final_prose=fixed, corrections=[{"rule_violated": "f", "reasoning": "r"}]))
    a = AuditorEngine(llm)
    out, report = await a.audit(prose, "search", language="en")
    assert out == fixed
    assert report["prose_rewritten"] is True


@pytest.mark.asyncio
async def test_marker_guard_rejects_altered_add_fields_when_name_has_bracket():
    # Regression: a ']' inside the ADD name must not let a category/source change slip
    # past the guard (guard regex must match the downstream parser grammar).
    prose = "You take it. [ITEM_ADD:Master Key [Vault 7]|tool|found in the crypt]"
    llm = _FakeLLM(_reply(
        verdict="corrected",
        final_prose="You take the key. [ITEM_ADD:Master Key [Vault 7]|relic|stolen from the king]",
        corrections=[{"rule_violated": "form", "reasoning": "x"}],
    ))
    a = AuditorEngine(llm)
    out, report = await a.audit(prose, "take it", language="en")
    assert out == prose
    assert report.get("marker_guard_rejected") is True


@pytest.mark.asyncio
async def test_corrected_with_empty_final_prose_keeps_original():
    prose = "The gate opens."
    llm = _FakeLLM(_reply(verdict="corrected", final_prose="", corrections=[]))
    a = AuditorEngine(llm)
    out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["prose_rewritten"] is False


@pytest.mark.asyncio
async def test_corrected_identical_prose_keeps_original():
    prose = "The gate opens."
    llm = _FakeLLM(_reply(verdict="corrected", final_prose="The gate opens.", corrections=[]))
    a = AuditorEngine(llm)
    out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["prose_rewritten"] is False


@pytest.mark.asyncio
async def test_pre_emit_audit_is_discarded_from_report():
    llm = _FakeLLM(_reply(
        verdict="clean",
        corrections=[],
        pre_emit_audit={"whatever": "scratchpad"},
    ))
    a = AuditorEngine(llm)
    _, report = await a.audit("The gate opens.", "x", language="en")
    assert "pre_emit_audit" not in report


@pytest.mark.asyncio
async def test_max_tokens_headroom_scales_with_turn_budget():
    llm = _FakeLLM(_reply(verdict="clean"))
    a = AuditorEngine(llm)
    await a.audit("The gate opens.", "x", language="en", max_tokens=3000)
    assert llm.last_max_tokens == 3000 + 2000 + 8000


@pytest.mark.asyncio
async def test_default_reasoning_headroom_gives_12000_for_default_turn_budget():
    llm = _FakeLLM(_reply(verdict="clean"))
    a = AuditorEngine(llm)
    await a.audit("The gate opens.", "x", language="en", max_tokens=2000)
    assert llm.last_max_tokens == 12000


@pytest.mark.asyncio
async def test_empty_output_releases_original_and_logs_error(caplog):
    llm = _FakeLLM("")
    a = AuditorEngine(llm)
    prose = "The gate opens."
    with caplog.at_level(logging.ERROR):
        out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["error"] == "empty_output"
    assert any(
        record.levelno == logging.ERROR and "EMPTY output" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_non_json_output_releases_original_and_logs_error(caplog):
    llm = _FakeLLM("bla bla")
    a = AuditorEngine(llm)
    prose = "The gate opens."
    with caplog.at_level(logging.ERROR):
        out, report = await a.audit(prose, "x", language="en")
    assert out == prose
    assert report["error"] == "parse_failed"
    assert any(record.levelno == logging.ERROR for record in caplog.records)


@pytest.mark.asyncio
async def test_ptbr_language_selects_ptbr_system_and_passes_language_context():
    llm = _FakeLLM(_reply(verdict="clean"))
    a = AuditorEngine(llm)
    await a.audit("O portão se abre.", "abrir o portão", language="pt-br")
    system = llm.last_messages[0]["content"]
    user = llm.last_messages[1]["content"]
    assert llm.last_messages[0]["role"] == "system"
    assert "Brazilian Portuguese" in user  # language name surfaced to the model
