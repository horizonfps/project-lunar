from unittest.mock import MagicMock

from app.services.game_session import GameSession


HEADER = "D+0 | Ano Imperial 1285/3/1 | Segunda-feira | 09:14 | 🌤️ | Praça do Grande Salão"
LATER = "D+0 | Ano Imperial 1285/3/1 | Segunda-feira | 09:16 | 🌤️ | Praça do Grande Salão"


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


def test_unclosed_speech_line_counts_as_truncated():
    assert not GameSession._is_response_complete('Ela virou.\n\n💬 @Lilia | "')


def test_closed_speech_line_counts_as_complete():
    assert GameSession._is_response_complete('💬 @Lilia | "Cinco em ponto."')


def test_continuation_drops_a_re_emitted_header():
    original = f"{HEADER}\n\nAdiante, o bloco"
    continuation = f"{LATER}\n\nda trilha da espada terminou de se alinhar."
    assert GameSession._splice_continuation(original, continuation) == (
        f"{HEADER}\n\nAdiante, o bloco da trilha da espada terminou de se alinhar."
    )


def test_continuation_without_a_header_is_appended_verbatim():
    original = f"{HEADER}\n\nEle abriu a"
    assert GameSession._splice_continuation(original, " porta.") == (
        f"{HEADER}\n\nEle abriu a porta."
    )


def test_continuation_restores_the_space_lost_at_the_cut():
    original = f"{HEADER}\n\nEle podia sair dali sem preparo"
    assert GameSession._splice_continuation(original, "nenhum.") == (
        f"{HEADER}\n\nEle podia sair dali sem preparo nenhum."
    )


def test_continuation_restores_the_space_after_a_comma():
    assert GameSession._splice_continuation("varreu a ala esquerda,", "depois a direita.") == (
        "varreu a ala esquerda, depois a direita."
    )


def test_continuation_starting_on_punctuation_is_not_spaced():
    assert GameSession._splice_continuation("Ela parou", '." O salão calou.') == (
        'Ela parou." O salão calou.'
    )


def test_continuation_after_a_hyphen_is_not_spaced():
    assert GameSession._splice_continuation("os estandartes azul-", "escuros pendiam.") == (
        "os estandartes azul-escuros pendiam."
    )


def test_header_only_continuation_leaves_the_prose_untouched():
    original = f"{HEADER}\n\nEle parou."
    assert GameSession._splice_continuation(original, f"{LATER}\n\n") == original
