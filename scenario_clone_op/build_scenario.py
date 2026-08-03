"""Build a Project Lunar import JSON from the AI Dungeon One Piece scenario.

Inputs:
- ../adventure-Xns2aTtTKtbE-story-cards-882.json  (raw AI Dungeon export)
- step{N}_raw.json captures from the AID wizard walkthrough (steps 5-14)
- setup_steps.json (steps 1-4 already authored)

Output:
- one_piece_adventures_lunar.json  (ready for POST /scenarios/import)
"""
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
SRC_CARDS = Path(r"C:/Users/iury2/Downloads/adventure-Xns2aTtTKtbE-story-cards-882.json")
OUT = ROOT / "one_piece_adventures_lunar.json"


# ---------- Build setup_questions from wizard captures ----------

def _load_step(filename: str) -> dict:
    return json.loads((ROOT / filename).read_text(encoding="utf-8"))


def _options_from_cards(cards: list[dict]) -> list[dict]:
    """AID card -> Project Lunar SetupOption."""
    out = []
    seen = set()
    for c in cards:
        label = (c.get("title") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        desc = (c.get("description") or "").strip()
        # Trim "SHOW MORE" sentinel that AID adds for long cards
        if desc.endswith(" SHOW MORE"):
            desc = desc[: -len(" SHOW MORE")].strip()
        out.append({"label": label, "description": desc})
    return out


def build_setup_questions() -> list[dict]:
    # Step 1: text — character name
    q1 = {
        "id": "q_name",
        "var_name": "character_name",
        "type": "text",
        "prompt": "What is your character's name?",
        "options": [],
        "allow_custom": False,
        "required": True,
    }
    # Step 2: choice — gender
    q2 = {
        "id": "q_gender",
        "var_name": "gender",
        "type": "choice",
        "prompt": "{character_name}, what is your gender?",
        "options": [
            {"label": "Male", "description": ""},
            {"label": "Female", "description": ""},
        ],
        "allow_custom": True,
        "required": True,
    }
    # Step 3: race (cards captured from wizard, but full list also lives in story-cards)
    raw_races = _load_step("step3_race_options.json")["options"]
    # The step3 file uses {title, description}; normalize to {label, description}.
    races = [{"label": r.get("title") or r.get("label", ""), "description": r.get("description", "")} for r in raw_races]
    q3 = {
        "id": "q_race",
        "var_name": "race",
        "type": "choice",
        "prompt": "Choose your race.",
        "options": races,
        "allow_custom": True,
        "required": True,
    }
    # Step 4: primary class
    q4_cards = _load_step("step4_class_options.json")["cards"]
    q4 = {
        "id": "q_class",
        "var_name": "class",
        "type": "choice",
        "prompt": "Choose your class.",
        "options": _options_from_cards(q4_cards),
        "allow_custom": True,
        "required": True,
    }
    # Step 5: starting location — wizard capture wasn't persisted; the story-cards JSON
    # is the source of truth, so derive the option list from cards of type "location".
    raw_cards = json.loads(SRC_CARDS.read_text(encoding="utf-8"))
    location_options = _options_from_cards([
        {"title": c.get("title", ""), "description": c.get("value", "") or c.get("description", "")}
        for c in raw_cards if c.get("type") == "location"
    ])
    q5 = {
        "id": "q_location",
        "var_name": "starting_location",
        "type": "choice",
        "prompt": "Where does your adventure begin?",
        "options": location_options,
        "allow_custom": True,
        "required": True,
    }
    # Step 6: faction
    q6 = {
        "id": "q_faction",
        "var_name": "faction",
        "type": "choice",
        "prompt": "Which faction or crew do you belong to?",
        "options": _options_from_cards(_load_step("step6_faction.json")["cards"]),
        "allow_custom": True,
        "required": True,
    }
    # Step 7: starting weapon
    q7 = {
        "id": "q_weapon",
        "var_name": "weapon",
        "type": "choice",
        "prompt": "Choose your starting weapon.",
        "options": _options_from_cards(_load_step("step7_raw.json")["cards"]),
        "allow_custom": True,
        "required": True,
    }
    # Step 8: devil fruit
    q8 = {
        "id": "q_devil_fruit",
        "var_name": "devil_fruit",
        "type": "choice",
        "prompt": "Choose your starting Devil Fruit.",
        "options": _options_from_cards(_load_step("step8_raw.json")["cards"]),
        "allow_custom": True,
        "required": True,
    }
    # Step 9: family
    q9 = {
        "id": "q_family",
        "var_name": "family",
        "type": "choice",
        "prompt": "Tell me, who will be your family?",
        "options": _options_from_cards(_load_step("step9_raw.json")["cards"]),
        "allow_custom": True,
        "required": True,
    }
    # Step 10: status
    q10 = {
        "id": "q_status",
        "var_name": "status",
        "type": "choice",
        "prompt": "What is your status in the world?",
        "options": _options_from_cards(_load_step("step10_raw.json")["cards"]),
        "allow_custom": False,
        "required": True,
    }
    # Step 11: worst generation
    q11 = {
        "id": "q_worst_gen",
        "var_name": "worst_generation",
        "type": "choice",
        "prompt": "Are you part of the Worst Generation?",
        "options": [
            {"label": "No", "description": ""},
            {"label": "Yes", "description": ""},
        ],
        "allow_custom": False,
        "required": True,
    }
    # Step 12: secondary class
    q12 = {
        "id": "q_class2",
        "var_name": "secondary_class",
        "type": "choice",
        "prompt": "What's your secondary class? (optional - choose None for a single specialty)",
        "options": _options_from_cards(_load_step("step12_raw.json")["cards"]),
        "allow_custom": True,
        "required": True,
    }
    # Step 13: bounty
    q13 = {
        "id": "q_bounty",
        "var_name": "bounty",
        "type": "choice",
        "prompt": "Choose your starting bounty.",
        "options": _options_from_cards(_load_step("step13_raw.json")["cards"]),
        "allow_custom": False,
        "required": True,
    }
    # Step 14: age
    q14 = {
        "id": "q_age",
        "var_name": "age_stage",
        "type": "choice",
        "prompt": "Are you starting as an Adult, Teen, or Child?",
        "options": _options_from_cards(_load_step("step14_raw.json")["cards"]),
        "allow_custom": False,
        "required": True,
    }

    return [q1, q2, q3, q4, q5, q6, q7, q8, q9, q10, q11, q12, q13, q14]


# ---------- Build story_cards from AID export ----------

# Map AID card type -> Project Lunar StoryCardType
TYPE_MAP = {
    "character": "NPC",
    "location": "LOCATION",
    "faction": "FACTION",
    "race": "LORE",
    "class": "LORE",
    "Choose your Starting Devil Fruit": "ITEM",
    "Choose your Starting Weapon": "ITEM",
    "Tell Me, Who will be your Family?": "FACTION",
    "What's your second Class?": "LORE",
    "Choose your starting bounty": "LORE",
    "What's your status?": "LORE",
    # Wizard-only types are dropped (handled by setup_questions)
}
DROP_TYPES = {
    "Are you starting as an Adult, Teen or Child?",
    "Are you a Marine or a Pirate or a Civilian.",
    "Are you a Marine or a Pirate",
    "Are you apart of the worst generation?",
    "Are you starting as an Adult or An Child?",
    "Are you starting as an Adult, Tenn, or an Child.",
}


def build_story_cards() -> list[dict]:
    raw = json.loads(SRC_CARDS.read_text(encoding="utf-8"))
    out = []
    seen = set()  # (card_type, name) — dedupe across "class" / "What's your second Class?" etc.
    skipped_empty = 0
    skipped_drop = 0
    skipped_dup = 0
    for c in raw:
        aid_type = c.get("type", "")
        if aid_type in DROP_TYPES:
            skipped_drop += 1
            continue
        if aid_type not in TYPE_MAP:
            skipped_drop += 1
            continue
        name = (c.get("title") or c.get("keys") or "").strip()
        value = (c.get("value") or c.get("description") or "").strip()
        if not name or not value:
            skipped_empty += 1
            continue
        ct = TYPE_MAP[aid_type]
        key = (ct, name)
        if key in seen:
            skipped_dup += 1
            continue
        seen.add(key)
        keys = (c.get("keys") or "").strip()
        out.append({
            "card_type": ct,
            "name": name,
            "content": {
                "description": value,
                "source_type": aid_type,
                "trigger_keys": keys,
            },
        })
    print(f"  built {len(out)} cards (skipped: {skipped_empty} empty, {skipped_drop} dropped types, {skipped_dup} duplicates)")
    return out


# ---------- Tone & opening ----------

TONE = """\
You are the Narrator of an open-ended One Piece adventure.

VOICE & STYLE
- Shōnen adventure tone: heroic, hot-blooded, full of dreams and camaraderie, with bursts of comedy.
- Vivid sensory descriptions of ships, sea, food, exotic islands, and over-the-top fights.
- Combat is cinematic, named-attack heavy ("Gomu Gomu no…", "Santoryu…", "Diable Jambe…").
- NPCs have strong personalities and quirks. Side characters react in distinct ways; they are not background props.
- Treat the player's choices as canonical. Never override what the player declares about themselves.

WORLD RULES
- The world is the canon One Piece world: Four Blues, Reverse Mountain, Grand Line, Red Line, New World, Sky Islands, Fish-Man Island, Calm Belts, Mary Geoise, Marineford, Impel Down, Sabaody Archipelago, Wano, Whole Cake Island, Onigashima, Egghead, Elbaf.
- Devil Fruits give a single power to one user; once eaten, the user can no longer swim — saltwater immobilizes them. A user cannot eat a second Devil Fruit (with the very rare canonical Blackbeard exception).
- Haki: Observation, Armament, and Conqueror's exist. Conqueror's is rare and only ~1 in a million wield it.
- The Marines, World Government, Cipher Pol, the Seven Warlords system (where active), the Yonko, the Revolutionary Army, and the Celestial Dragons all exert pressure on the world's politics.
- Sea Kings inhabit the Calm Belts. Log Poses are required to navigate the Grand Line. Eternal Poses lock onto a single island.
- Bounties scale with infamy and threat to the World Government, not raw power.

NARRATIVE BEHAVIOR
- Keep narration in second person ("You…") unless the player switches voice.
- After each player action, narrate consequences, NPC reactions, and environmental changes — then end on a hook or question that invites the next action.
- Honor the player's stats: chosen race, class(es), weapon, Devil Fruit, family, faction, status, bounty, and age. Use them to flavor encounters.
- Track injuries, hunger, fatigue, and emotional state across turns. Don't reset them between scenes.
- When the player attempts something far beyond their power level, narrate the strain — don't auto-grant success.
- Surface story-card NPCs, locations, factions, and items when the player is in their orbit. Stay faithful to their canonical descriptions in the story cards.
- Comic relief is welcome (Luffy-style appetite, Zoro getting lost, Usopp's tall tales) — but never undercut a dramatic beat with it.

CONTENT
- PG-13 violence: blood and consequences, but no gratuitous gore.
- Romance is allowed if the player initiates; keep it tasteful.
- Allow player-driven moral grayness. Pirates are not strictly evil; Marines are not strictly good.
"""

OPENING = """\
The salt wind hits your face before your eyes are even open.

A gull cries somewhere overhead. Planks creak under your feet; ahead, the horizon stretches in every direction — endless, blue, and dangerous. Today is the day your name finally goes on the tide.

Twenty-something years ago Gold Roger stood on the executioner's stage in Loguetown and laughed. He told the world his treasure existed and waited for anyone bold enough to find it, and the world has been bleeding pirates ever since. The Four Seas; Reverse Mountain rising like a brass spine into the clouds; the Grand Line winding past Sabaody, the Red Line, Fish-Man Island; and somewhere far beyond Mary Geoise — the New World, where Yonko reign and weather changes its mind every five minutes. At the end of all of it, Laugh Tale. The One Piece.

People kill for less. Empires have been built on whispers of less.

The Marines have your name on a bulletin somewhere. The World Government has filed it. Your faction knows what you've sworn to do, and so do you. Your weapon catches the morning light. Whatever powers you've got — earned or eaten — sit in your bones, ready.

A shadow falls over you as a fellow sailor leans against the rail. They glance at you, then at the open water, then back.

"So," they say, voice low enough to be private. "Where are we going?"

The sea is waiting.
"""

LORE = """\
WORLD-LEVEL CONTEXT (ambient — don't dump on the player; reveal through play)

THE FOUR SEAS
- East Blue: weakest sea. Birthplace of legends — Roger, Luffy, Zoro, Sanji, Nami, Usopp.
- West Blue: strong underworld families and dangerous shipping lanes.
- North Blue: cold, militarized kingdoms. Germa, Flevance, the Vinsmokes.
- South Blue: warm, lively, full of ancient ruins and unstable politics.

THE GRAND LINE
- Reverse Mountain links the Four Blues to the Grand Line.
- Paradise: the first half of the Grand Line — already deadly.
- New World: the second half, where the Yonko rule and weather changes by the minute.
- Calm Belts flank the Grand Line and are infested by Sea Kings.

POWER SYSTEMS
- Devil Fruits: Paramecia (alter user/matter), Zoan (animal transformations + Mythical/Ancient subtypes), Logia (elemental intangibility). One per user. Saltwater = paralysis.
- Haki: Observation (sense), Armament (defense/offense, hits Logia), Conqueror's (will, ~1 in a million).
- Six Powers (Rokushiki): elite martial art used by CP9 and similar.
- Fish-Man Karate / Black Leg / Three-Sword Style / etc. — named martial styles.

FACTIONS (high level)
- Marines: World Government's military arm. Three Admirals, Vice Admirals, Captains, ranks below.
- World Government: 170+ affiliated nations. The Five Elders sit at the top under Imu.
- Celestial Dragons / Tenryuubito: nobles in Mary Geoise. Untouchable by law.
- Cipher Pol: government intelligence. CP-0 outranks the others.
- Yonko: four pirate emperors who carve up the New World among themselves.
- Revolutionary Army: opposes the Celestial Dragons and the World Government.
- Seven Warlords: government-sanctioned pirates (status varies by era).
- Worst Generation: the rookie pirates who entered the New World together — a bounty cohort.

ECONOMY & TRAVEL
- Berries (₿) — the global currency.
- Log Pose: required to navigate the Grand Line; locks onto islands' magnetic fields.
- Eternal Pose: permanently locked onto one specific island.
- Vivre Card: paper that points to a person's current location, decays as they take damage.
"""


def main():
    print("[1/3] Building setup_questions from wizard captures…")
    questions = build_setup_questions()
    for q in questions:
        n = len(q["options"]) if q["type"] == "choice" else 0
        print(f"  - {q['var_name']:<20} ({q['type']}, {n} options)")

    print("[2/3] Building story_cards from AID export…")
    cards = build_story_cards()

    print("[3/3] Writing import JSON…")
    payload = {
        "version": "1.0",
        "scenario": {
            "title": "One Piece: Adventures",
            "description": "An open-ended One Piece adventure across the Four Blues, the Grand Line, and the New World. Pick your race, class, weapon, Devil Fruit, family, faction, and bounty — then sail.",
            "tone_instructions": TONE,
            "opening_narrative": OPENING,
            "language": "en",
            "lore_text": LORE,
            "setup_questions": questions,
        },
        "story_cards": cards,
        "campaigns": [],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"\nDone -> {OUT}  ({size_kb:.1f} KB, {len(cards)} cards, {len(questions)} questions)")


if __name__ == "__main__":
    main()
