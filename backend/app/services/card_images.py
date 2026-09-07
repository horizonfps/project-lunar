"""Pick a character card image to show alongside a narrator turn.

Scenario authors attach art to an NPC story card via `content["images"]`, a list
of URLs relative to the /media mount. A card is shown when its NPC appears in
the narrative and has not been shown for the last COOLDOWN_TURNS turns, so
recurring characters do not repeat their portrait every message.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

COOLDOWN_TURNS = 5


@dataclass
class CardImage:
    name: str
    url: str
    caption: str


def _card_type(card) -> str:
    card_type = getattr(card, "card_type", "")
    return getattr(card_type, "value", str(card_type)).upper()


def _images_of(card) -> list[str]:
    content = getattr(card, "content", None)
    if not isinstance(content, dict):
        return []
    images = content.get("images")
    if isinstance(images, str):
        images = [images]
    if not isinstance(images, list):
        return []
    return [u for u in images if isinstance(u, str) and u.strip()]


def _mentions(name: str, text: str) -> list:
    return list(re.finditer(rf"\b{re.escape(name)}\b", text, re.IGNORECASE))


def _appears_in(name: str, text: str) -> bool:
    return bool(_mentions(name, text))


def select_card_image(
    story_cards: list,
    narrative_text: str,
    turn_count: int,
    last_shown: dict[str, int],
    rng: random.Random | None = None,
) -> CardImage | None:
    """Return art for the NPC carrying the scene.

    Among the eligible NPCs, one making their first appearance wins over a
    returning one, then the NPC named most often, then the one named earliest.
    `last_shown` maps NPC name to the turn its art was last displayed and is
    updated in place when an image is selected.
    """
    if not narrative_text or not story_cards:
        return None

    best = None
    best_key = None
    for card in story_cards:
        if _card_type(card) != "NPC":
            continue
        images = _images_of(card)
        if not images:
            continue
        name = (getattr(card, "name", "") or "").strip()
        if not name:
            continue
        hits = _mentions(name, narrative_text)
        if not hits:
            continue
        previous = last_shown.get(name)
        if previous is not None and turn_count - previous < COOLDOWN_TURNS:
            continue

        key = (previous is not None, -len(hits), hits[0].start())
        if best_key is None or key < best_key:
            best_key, best = key, (name, card, images)

    if best is None:
        return None

    name, card, images = best
    content = card.content if isinstance(card.content, dict) else {}
    picked = (rng or random).choice(images)
    last_shown[name] = turn_count
    return CardImage(
        name=name,
        url=picked,
        caption=str(content.get("title") or content.get("role") or "").strip(),
    )
