import logging

import pytest

from app.services.scenario_interpolation import interpolate, reset_warning_cache


@pytest.fixture(autouse=True)
def _clear_warning_cache():
    reset_warning_cache()
    yield
    reset_warning_cache()


def _ans(value: str) -> dict:
    return {"value": value}


def test_basic_substitution():
    answers = {"character_name": _ans("Monkey D. Test"), "race": _ans("human")}
    assert interpolate(
        "You are {character_name}, a {race}.", answers,
    ) == "You are Monkey D. Test, a human."


def test_missing_variable_preserves_literal():
    out = interpolate("Hello {character_name}.", {})
    assert out == "Hello {character_name}."


def test_missing_variable_emits_one_warning_per_pair(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.scenario_interpolation")
    interpolate("{a} {b} {a}", {}, context="ctx")
    interpolate("{a} {b}", {}, context="ctx")  # second call, same context+vars
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # First call covers both vars; the second call should emit nothing new.
    assert len(warnings) == 1
    assert "['a', 'b']" in warnings[0].getMessage()


def test_double_brace_escape_literally():
    answers = {"name": _ans("Sora")}
    template = "Hello {name}, here is JSON: {{\"k\": {{\"v\": 1}}}}"
    out = interpolate(template, answers)
    assert out == 'Hello Sora, here is JSON: {"k": {"v": 1}}'


def test_backslash_escape_skips_substitution():
    answers = {"name": _ans("Sora")}
    out = interpolate("code: \\{name} resolved: {name}", answers)
    assert out == "code: {name} resolved: Sora"


def test_non_dict_answer_values_tolerated():
    answers = {"a": "plain", "b": 42, "c": None}
    out = interpolate("{a}/{b}/{c}", answers)
    # `c` is None → treated as missing → literal preserved.
    assert out == "plain/42/{c}"


def test_recursion_is_single_pass():
    # If `{a}` resolves to `{b}`, we MUST NOT then expand `{b}`.
    answers = {"a": _ans("{b}"), "b": _ans("INNER")}
    assert interpolate("{a}", answers) == "{b}"


def test_empty_template_returns_empty():
    assert interpolate("", {"x": _ans("y")}) == ""
    assert interpolate(None, {}) == ""  # type: ignore[arg-type]


def test_blank_value_treated_as_missing():
    answers = {"name": _ans("   ")}
    out = interpolate("Hello {name}.", answers)
    assert out == "Hello {name}."


def test_uppercase_var_names_are_not_matched():
    # Var names lowercase-only matches the wizard's regex.
    out = interpolate("{NAME}", {"NAME": _ans("X")})
    assert out == "{NAME}"
