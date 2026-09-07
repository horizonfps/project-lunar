import pytest

from app.engines.narrator_engine import NarratorEngine


def test_paragraph_budget_tightens_with_the_token_budget():
    assert NarratorEngine._paragraph_budget(400) == 2
    assert NarratorEngine._paragraph_budget(768) == 3
    assert NarratorEngine._paragraph_budget(1200) == 5
    assert NarratorEngine._paragraph_budget(2000) == 7
    assert NarratorEngine._paragraph_budget(4000) == 0


def test_generous_budget_drops_only_the_paragraph_count():
    for language, count in (("en", "narration paragraphs"), ("pt-br", "parágrafos de narração")):
        text = NarratorEngine._length_instruction(4000, language)
        assert count not in text
        assert "COMPLETE" in text or "COMPLETA" in text


def test_unknown_budget_emits_nothing():
    assert NarratorEngine._length_instruction(0) == ""
    assert NarratorEngine._length_instruction(0, "pt-br") == ""


def test_instruction_names_the_paragraph_budget_and_spending_order():
    text = NarratorEngine._length_instruction(768)
    assert "at most 3 narration paragraphs" in text
    assert "Spend the budget in this order" in text
    assert "Ambient description gets what is left over" in text


# The slider spans 256-8192, so the rules that do not depend on a paragraph
# count have to hold across the whole range rather than at one setting.
@pytest.mark.parametrize("max_tokens", [256, 400, 768, 1000, 1200, 2000, 3000, 3001, 4000, 8192])
@pytest.mark.parametrize("language", ["en", "pt-br"])
def test_spending_order_and_hard_limit_hold_at_every_size(max_tokens, language):
    text = NarratorEngine._length_instruction(max_tokens, language)
    assert f"{max_tokens} tokens" in text
    assert ("Spend the budget in this order" in text) or ("Gaste o orçamento nesta ordem" in text)
    assert ("not a target" in text) or ("não é meta" in text)


def test_instruction_follows_the_campaign_language():
    assert "parágrafos de narração" in NarratorEngine._length_instruction(768, "pt-br")
    assert "narration paragraphs" in NarratorEngine._length_instruction(768, "en")


def test_directive_reaches_the_volatile_zone_in_campaign_language():
    engine = NarratorEngine.__new__(NarratorEngine)
    assert "parágrafos de narração" in engine.length_directive(768, "pt-br")


def test_rules_block_carries_the_instruction_in_its_own_language():
    engine = NarratorEngine.__new__(NarratorEngine)
    assert "parágrafos de narração" in engine._build_narrator_rules(768, "pt-br")
    assert "narration paragraphs" in engine._build_narrator_rules(768, "en")


def test_cached_zone_omits_the_length_instruction():
    engine = NarratorEngine.__new__(NarratorEngine)
    rules = engine._build_narrator_rules(768, "pt-br", include_length=False)
    assert "parágrafos de narração" not in rules
