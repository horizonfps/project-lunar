from app.engines.narrator_engine import NarratorEngine


def test_paragraph_budget_tightens_with_the_token_budget():
    assert NarratorEngine._paragraph_budget(400) == 2
    assert NarratorEngine._paragraph_budget(768) == 3
    assert NarratorEngine._paragraph_budget(1200) == 5
    assert NarratorEngine._paragraph_budget(2000) == 7
    assert NarratorEngine._paragraph_budget(4000) == 0


def test_generous_budget_drops_the_constraint():
    assert NarratorEngine._length_instruction(4000) == ""
    assert NarratorEngine._length_instruction(4000, "pt-br") == ""


def test_instruction_names_the_paragraph_budget_and_cut_order():
    text = NarratorEngine._length_instruction(768)
    assert "at most 3 narration paragraphs" in text
    assert "ambient description first" in text


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
