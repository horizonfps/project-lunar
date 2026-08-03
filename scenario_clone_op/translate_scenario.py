"""
Translates a Project Lunar scenario JSON from English to Brazilian Portuguese
using OpenAI GPT-4o.

Usage:
    OPENAI_API_KEY=... python translate_scenario.py \
        --input one_piece_adventures_lunar.json \
        --output one_piece_adventures_lunar.pt-br.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

MODEL = "gpt-4o"
TARGET_LANGUAGE = "Brazilian Portuguese (pt-BR)"
CARDS_PER_BATCH = 5
MAX_WORKERS = 1  # 30k TPM org limit — keep serial; bump if your tier is higher
MAX_RETRIES = 6
MIN_INTERVAL_SEC = 4.0  # gap between API calls (~15/min ≈ safe under 30k TPM)

GLOSSARY_RULES = """\
TRANSLATION RULES (One Piece scenario → Brazilian Portuguese):

1. KEEP UNTRANSLATED (proper names of characters, crews, organizations, fruits in
   Japanese, named techniques):
   - Character names: Luffy, Zoro, Sanji, Nami, Usopp, Aokiji, Akainu, Kizaru,
     Roger, Whitebeard, Blackbeard, Shanks, Vegapunk, Imu, etc.
   - Crews / factions kept in original form: Red-Hair Pirates, Blackbeard Pirates,
     Worst Generation, CP-0, CP9, Cipher Pol, Yonko, Tenryuubito, Vinsmoke, Germa.
   - Devil Fruit Japanese names: Gomu Gomu no Mi, Hito Hito no Mi, Mera Mera no Mi.
   - Named techniques: Santoryu, Diable Jambe, Gear Second, Conqueror's Haki
     (you may render as "Haki do Conquistador").
   - Place names that are proper nouns: Loguetown, Sabaody, Mary Geoise, Marineford,
     Impel Down, Wano, Dressrosa, Onigashima, Egghead, Elbaf, Foosha Village,
     Dawn Island, Reverse Mountain, Red Line, Grand Line, New World, Calm Belt,
     Fish-Man Island, Sky Island.
   - Currency: keep "Berries" / "₿".

2. TRANSLATE (descriptive English nouns and prose):
   - Generic terms: "Marines" → "Marinha"; "World Government" → "Governo Mundial";
     "Revolutionary Army" → "Exército Revolucionário"; "Seven Warlords" →
     "Sete Corsários"; "Celestial Dragons" → "Dragões Celestiais"; "Admiral" →
     "Almirante"; "Vice Admiral" → "Vice-Almirante"; "Captain" → "Capitão".
   - Race names: "Human" → "Humano"; "Fish-Men" → "Homens-Peixe"; "Merfolk" →
     "Sereianos"; "Sky Islanders" → "Ilhéus Celestes"; "Minks" → "Minks";
     "Giants" → "Gigantes"; "Lunarians" → "Lunarianos"; "Cyborgs" → "Ciborgues";
     "Skeleton" → "Esqueleto"; "Artificial Humans" → "Humanos Artificiais";
     "Wotans" → "Wotans"; "Longarm Tribe" → "Tribo Braço-Longo";
     "Longleg Tribe" → "Tribo Perna-Longa".
   - Devil Fruit *English nicknames* should be translated (e.g., "Slow-Slow Fruit"
     → "Fruta Slow-Slow"; "Rumble-Rumble Fruit" → "Fruta Rumble-Rumble").
   - Job/class names, item descriptions, and prose text → translate naturally.

3. STRUCTURE / IDS:
   - NEVER translate JSON keys.
   - NEVER translate values that look like identifiers, enums, or system codes
     (card_type, source_type, var_name, id, type field values like "text"/"choice").
   - When a `name` field is translated, the matching `trigger_keys` field MUST be
     translated identically (same surface form), so triggers keep working.
   - Preserve all line breaks (\\n) and Markdown-ish formatting.

4. STYLE: Use natural, fluent Brazilian Portuguese. Match the heroic shōnen tone
   of the source. Keep second-person narration ("Você...") where the source uses
   "You...".
"""

client: OpenAI | None = None
_last_call_ts: float = 0.0
_throttle_lock = __import__("threading").Lock()


def _throttle() -> None:
    global _last_call_ts
    with _throttle_lock:
        delta = time.monotonic() - _last_call_ts
        if delta < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - delta)
        _last_call_ts = time.monotonic()


def call_chat(system: str, user: str, json_mode: bool) -> str:
    assert client is not None
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            kwargs = {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            _throttle()
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)
            is_rate = "429" in msg or "rate_limit" in msg.lower() or "tokens per min" in msg.lower()
            wait = 30 if is_rate else 2 ** attempt
            print(f"  ! API error (attempt {attempt + 1}/{MAX_RETRIES}): {msg[:160]} — "
                  f"retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_err}")


SYSTEM_PROSE = (
    f"You are a professional translator. Translate text from English into "
    f"{TARGET_LANGUAGE}.\n\n{GLOSSARY_RULES}\n\n"
    f"Output ONLY the translated text — no preamble, no quotes, no markdown fences."
)

SYSTEM_JSON = (
    f"You are a professional translator. Translate the provided JSON content from "
    f"English into {TARGET_LANGUAGE}.\n\n{GLOSSARY_RULES}\n\n"
    f"Output a single JSON object with exactly the same shape as the input. "
    f"Translate ONLY the string fields explicitly listed in the user's instruction. "
    f"Preserve all keys, ids, ordering, and untouched fields verbatim."
)


def translate_prose(text: str, what: str) -> str:
    if not text or not text.strip():
        return text
    out = call_chat(
        SYSTEM_PROSE,
        f"Translate the following {what} to {TARGET_LANGUAGE}. "
        f"Preserve all line breaks and any inline formatting.\n\n---\n{text}\n---",
        json_mode=False,
    ).strip()
    # Strip surrounding triple-backtick fences if model added them.
    if out.startswith("```"):
        out = out.strip("`")
        # Drop optional language tag on first line.
        if "\n" in out:
            first, rest = out.split("\n", 1)
            if len(first) <= 12 and not first.startswith(" "):
                out = rest
        out = out.strip()
    return out


def _translate_options_chunk(chunk: list[dict]) -> list[dict]:
    payload = {"options": chunk}
    instr = (
        "Translate each option's `label` and `description` only. "
        "Do not add or remove options. Preserve order.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    raw = call_chat(SYSTEM_JSON, instr, json_mode=True)
    out = json.loads(raw)["options"]
    if len(out) != len(chunk):
        raise RuntimeError(f"Option count mismatch: in={len(chunk)} out={len(out)}")
    return out


def translate_setup_questions(questions: list[dict]) -> list[dict]:
    """Translate one question at a time; chunk options if a question has many."""
    out: list[dict] = []
    for i, q in enumerate(questions, 1):
        q = dict(q)
        opts = q.get("options", [])
        print(f"  · question {i}/{len(questions)} ({q.get('id')}, {len(opts)} options)...")

        # Translate prompt + options in one call when small; otherwise split options.
        if len(opts) <= 8:
            payload = {"question": {"prompt": q["prompt"], "options": opts}}
            instr = (
                "Translate the question's `prompt`, and within `options` translate "
                "`label` and `description`. Preserve `{character_name}` and other "
                "`{var}` placeholders verbatim. Do not add/remove options.\n\n"
                f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            raw = call_chat(SYSTEM_JSON, instr, json_mode=True)
            translated = json.loads(raw)["question"]
            q["prompt"] = translated["prompt"]
            q["options"] = translated["options"]
        else:
            # Translate the prompt alone, then chunk options.
            instr = (
                "Translate the following question prompt. Preserve `{character_name}` "
                "and other `{var}` placeholders verbatim.\n\n"
                f"Input JSON:\n{json.dumps({'prompt': q['prompt']}, ensure_ascii=False)}"
            )
            raw = call_chat(SYSTEM_JSON, instr, json_mode=True)
            q["prompt"] = json.loads(raw)["prompt"]

            chunk_size = 10
            new_opts: list[dict] = []
            for j in range(0, len(opts), chunk_size):
                chunk = opts[j:j + chunk_size]
                new_opts.extend(_translate_options_chunk(chunk))
                print(f"    · options {j + len(chunk)}/{len(opts)} done")
            q["options"] = new_opts

        if len(q["options"]) != len(opts):
            raise RuntimeError(f"Question {q.get('id')} option count drift")
        out.append(q)
    return out


def translate_card_batch(batch: list[dict]) -> list[dict]:
    payload = {"cards": batch}
    instr = (
        "Translate each card's `name`, `content.description`, and "
        "`content.trigger_keys`. The translated `trigger_keys` MUST equal the "
        "translated `name` (same surface form). DO NOT modify `card_type` or "
        "`content.source_type`. Follow the glossary: keep canonical proper nouns "
        "untranslated.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    raw = call_chat(SYSTEM_JSON, instr, json_mode=True)
    out = json.loads(raw)["cards"]
    if len(out) != len(batch):
        raise RuntimeError(f"Card count mismatch: in={len(batch)} out={len(out)}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--limit-cards", type=int, default=0,
                        help="If > 0, only translate the first N cards (for testing).")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: no OPENAI_API_KEY provided", file=sys.stderr)
        return 2

    global client
    client = OpenAI(api_key=args.api_key)

    src = json.loads(Path(args.input).read_text(encoding="utf-8"))
    scen = src["scenario"]

    print(f"Translating scenario from '{scen.get('language')}' → pt-BR using {MODEL}")
    print(f"  Title:           {scen['title']!r}")
    print(f"  Story cards:     {len(src['story_cards'])}")
    print(f"  Setup questions: {len(scen['setup_questions'])}")

    # ---- Scenario-level prose fields -----------------------------------------
    print("\n[1/5] Translating title...")
    scen["title"] = translate_prose(scen["title"], "scenario title")
    print(f"  → {scen['title']!r}")

    print("[2/5] Translating description...")
    scen["description"] = translate_prose(scen["description"], "scenario description")

    print("[3/5] Translating tone_instructions, opening_narrative, lore_text...")
    for key, what in [
        ("tone_instructions", "scenario tone_instructions (Narrator system prompt)"),
        ("opening_narrative", "scenario opening_narrative"),
        ("lore_text", "scenario lore_text (world background)"),
    ]:
        scen[key] = translate_prose(scen[key], what)
        print(f"  ✓ {key}")

    scen["language"] = "pt"

    # ---- Setup questions -----------------------------------------------------
    print("[4/5] Translating setup questions...")
    scen["setup_questions"] = translate_setup_questions(scen["setup_questions"])
    print(f"  ✓ {len(scen['setup_questions'])} questions translated")

    # ---- Story cards (batched, parallel) -------------------------------------
    all_cards = src["story_cards"]
    cards = all_cards
    if args.limit_cards > 0:
        cards = all_cards[: args.limit_cards]
        print(f"  ! limit-cards={args.limit_cards} — translating only first {len(cards)} cards")

    batches = [cards[i:i + CARDS_PER_BATCH] for i in range(0, len(cards), CARDS_PER_BATCH)]
    print(f"[5/5] Translating {len(cards)} story cards in {len(batches)} "
          f"batches of {CARDS_PER_BATCH} (workers={MAX_WORKERS})...")

    translated_cards: list[dict | None] = [None] * len(batches)
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(translate_card_batch, b): i for i, b in enumerate(batches)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                translated_cards[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ batch {idx} failed: {e}", file=sys.stderr)
                raise
            completed += 1
            if completed % 5 == 0 or completed == len(batches):
                print(f"  ✓ {completed}/{len(batches)} batches done")

    flat: list[dict] = []
    for batch in translated_cards:
        flat.extend(batch or [])
    if args.limit_cards > 0:
        flat.extend(all_cards[len(flat):])
    src["story_cards"] = flat

    Path(args.output).write_text(
        json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
