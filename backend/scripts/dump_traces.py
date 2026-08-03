"""Dump LLM call traces saved in the trace DB, for offline inspection.

Run:  backend/venv/Scripts/python scripts/dump_traces.py [--campaign ID] [--limit N] [--turn N] [--full] [--json]
"""
from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.trace_store import TraceStore

DEFAULT_DB_PATH = os.environ.get(
    "LLM_TRACE_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "traces.db")
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect saved LLM call traces.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to the trace database.")
    parser.add_argument("--campaign", default=None, help="Campaign id to inspect.")
    parser.add_argument("--limit", type=int, default=3, help="Number of recent turns to print.")
    parser.add_argument("--turn", type=int, default=None, help="Print only this turn_index.")
    parser.add_argument("--full", action="store_true", help="Print full input section bodies.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of readable text.")
    return parser.parse_args()


def print_campaign_list(store: TraceStore) -> None:
    campaigns = store.list_campaigns()
    if not campaigns:
        print("No campaigns with saved traces found.")
        return
    print("=" * 70)
    print("Campaigns with saved traces")
    print("=" * 70)
    for c in campaigns:
        print(f"{c['campaign_id']:<30} turns={c['turns']:<6} last_created_at={c['last_created_at']}")


def print_section(section: dict, full: bool) -> None:
    title = section.get("title", "")
    body = section.get("body", "")
    truncated = section.get("truncated", False)
    if full:
        print(f"  --- {title} ---")
        print(body)
        if truncated:
            print("  [truncated]")
    else:
        flag = " [truncated]" if truncated else ""
        print(f"  - {title} ({len(body)} chars){flag}")


def print_entry(entry: dict, full: bool) -> None:
    usage = entry.get("usage", {})
    print("-" * 70)
    print(
        f"seq={entry.get('seq')} tag={entry.get('tag')} label={entry.get('label')} "
        f"model={entry.get('model')}"
    )
    print(
        f"  input={usage.get('input', 0)} output={usage.get('output', 0)} "
        f"cache_read={usage.get('cache_read', 0)} cache_creation={usage.get('cache_creation', 0)} "
        f"elapsed_s={entry.get('elapsed_s')}"
    )
    sections = entry.get("input", [])
    if sections:
        print("  input sections:")
        for section in sections:
            print_section(section, full)
    print("  output:")
    print(entry.get("output", ""))


def print_turn(turn: dict, full: bool) -> None:
    print("=" * 70)
    summary = turn.get("summary", {})
    print(
        f"turn_index={turn.get('turn_index')} created_at={turn.get('created_at')} "
        f"calls={len(turn.get('entries', []))} action={turn.get('action')}"
    )
    print(f"summary={summary}")
    for entry in turn.get("entries", []):
        print_entry(entry, full)


def main() -> int:
    args = parse_args()
    db_path = args.db

    if not os.path.exists(db_path):
        print(f"Trace database not found: {db_path}")
        return 1

    with TraceStore(db_path) as store:
        if not args.campaign:
            if args.json:
                print(json.dumps(store.list_campaigns(), ensure_ascii=False, indent=2))
            else:
                print_campaign_list(store)
            return 0

        fetch_limit = 10000 if args.turn is not None else args.limit
        turns = store.get_recent(args.campaign, fetch_limit)

        if args.turn is not None:
            turns = [t for t in turns if t.get("turn_index") == args.turn]

        if not turns:
            print(f"No traces found for campaign '{args.campaign}'.")
            return 0

        if not args.turn:
            turns = turns[-args.limit:]

        if args.json:
            print(json.dumps(turns, ensure_ascii=False, indent=2))
            return 0

        for turn in turns:
            print_turn(turn, args.full)

    return 0


if __name__ == "__main__":
    sys.exit(main())
