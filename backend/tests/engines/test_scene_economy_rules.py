import pytest

from app.engines.narrator_engine import NarratorEngine


@pytest.fixture
def engine():
    return NarratorEngine.__new__(NarratorEngine)


@pytest.mark.parametrize("language, heading", [("en", "SCENE ECONOMY"), ("pt-br", "ECONOMIA DE CENA")])
def test_scene_economy_survives_a_budget_that_drops_the_length_rule(engine, language, heading):
    assert heading in engine._build_narrator_rules(4000, language)


@pytest.mark.parametrize(
    "language, closing",
    [("en", "closing line of every response belongs to a person"),
     ("pt-br", "última linha de toda resposta pertence a uma pessoa")],
)
def test_response_must_close_on_a_person(engine, language, closing):
    assert closing in engine._build_narrator_rules(768, language)


@pytest.mark.parametrize(
    "language, rule",
    [("en", "Ambient description never occupies a paragraph of its own"),
     ("pt-br", "Descrição de ambiente nunca ocupa um parágrafo próprio")],
)
def test_ambient_description_cannot_own_a_paragraph(engine, language, rule):
    assert rule in engine._build_narrator_rules(768, language)


@pytest.mark.parametrize(
    "language, rule",
    [("en", "Size the response to the beat"), ("pt-br", "Dimensione a resposta pela batida")],
)
def test_response_length_scales_with_the_beat(engine, language, rule):
    assert rule in engine._build_narrator_rules(768, language)


@pytest.mark.parametrize("language", ["en", "pt-br"])
def test_no_rule_still_invites_a_settling_ambient_close(engine, language):
    rules = engine._build_narrator_rules(768, language)
    assert "where the scene breathes" not in rules
    assert "onde a cena respira" not in rules
    assert "at a natural pause" not in rules
    assert "em uma pausa natural" not in rules
