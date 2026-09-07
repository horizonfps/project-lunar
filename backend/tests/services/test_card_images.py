import random
from types import SimpleNamespace

from app.services.card_images import COOLDOWN_TURNS, select_card_image


def npc(name, images=None, **content):
    return SimpleNamespace(card_type="NPC", name=name, content={"images": images or [], **content})


def test_selects_npc_appearing_in_narrative():
    cards = [npc("Emily", ["/media/Emily/1.webp"], title="Principal")]
    image = select_card_image(cards, "Emily stepped to the podium.", 1, {})
    assert image.name == "Emily"
    assert image.url == "/media/Emily/1.webp"
    assert image.caption == "Principal"


def test_ignores_npc_not_mentioned():
    cards = [npc("Emily", ["/media/Emily/1.webp"])]
    assert select_card_image(cards, "The hall stood empty.", 1, {}) is None


def test_ignores_partial_word_match():
    cards = [npc("Emily", ["/media/Emily/1.webp"])]
    assert select_card_image(cards, "Emilyanne waved back.", 1, {}) is None


def test_ignores_card_without_images():
    cards = [npc("Emily")]
    assert select_card_image(cards, "Emily smiled.", 1, {}) is None


def test_ignores_non_npc_cards():
    location = SimpleNamespace(
        card_type="LOCATION", name="Grand Hall", content={"images": ["/media/hall.webp"]}
    )
    assert select_card_image([location], "The Grand Hall filled up.", 1, {}) is None


def test_respects_cooldown_then_shows_again():
    cards = [npc("Emily", ["/media/Emily/1.webp"])]
    seen = {}
    assert select_card_image(cards, "Emily spoke.", 1, seen) is not None
    assert select_card_image(cards, "Emily spoke again.", 1 + COOLDOWN_TURNS - 1, seen) is None
    assert select_card_image(cards, "Emily returned.", 1 + COOLDOWN_TURNS, seen) is not None


def test_cooldown_is_per_character():
    cards = [npc("Emily", ["/media/Emily/1.webp"]), npc("Rena", ["/media/Rena/1.webp"])]
    seen = {}
    assert select_card_image(cards, "Emily spoke.", 1, seen).name == "Emily"
    assert select_card_image(cards, "Emily and Rena talked.", 2, seen).name == "Rena"


def test_picks_from_available_variants():
    variants = [f"/media/Emily/{i}.webp" for i in range(1, 7)]
    cards = [npc("Emily", variants)]
    image = select_card_image(cards, "Emily arrived.", 1, {}, rng=random.Random(0))
    assert image.url in variants


def test_empty_inputs_return_none():
    assert select_card_image([], "Emily arrived.", 1, {}) is None
    assert select_card_image([npc("Emily", ["/media/Emily/1.webp"])], "", 1, {}) is None


def test_prefers_the_npc_carrying_the_scene():
    cards = [npc("Elise", ["/media/Elise/1.webp"]), npc("Lilia", ["/media/Lilia/1.webp"])]
    text = "Elise passed by. Lilia laughed. Lilia leaned in. Lilia asked again."
    assert select_card_image(cards, text, 1, {}).name == "Lilia"


def test_first_appearance_outranks_a_returning_npc():
    cards = [npc("Elise", ["/media/Elise/1.webp"]), npc("Lilia", ["/media/Lilia/1.webp"])]
    text = "Elise passed by. Lilia laughed. Lilia leaned in. Lilia asked again."
    seen = {"Lilia": 1}
    assert select_card_image(cards, text, 2, seen).name == "Elise"


def test_earliest_mention_breaks_a_tie():
    cards = [npc("Elise", ["/media/Elise/1.webp"]), npc("Lilia", ["/media/Lilia/1.webp"])]
    assert select_card_image(cards, "Lilia nodded. Elise nodded.", 1, {}).name == "Lilia"
