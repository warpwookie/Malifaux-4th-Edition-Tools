#!/usr/bin/env python3
"""
backfill_crew_tokens.py — Extract token definitions from existing crew card back PNGs.

All crew card back PNGs already exist in pipeline_work/. This script:
1. Finds all *Crew*_back.png files
2. Sends each to Claude API with crew_card_back_prompt
3. Matches extracted tokens to existing crew_cards in DB by name
4. Updates crew_tokens table (delete existing, insert new)

Usage:
    python backfill_crew_tokens.py --dry-run        # Extract only, don't update DB
    python backfill_crew_tokens.py --apply           # Extract and update DB
    python backfill_crew_tokens.py --faction Bayou --apply  # Single faction
"""
import argparse
import json
import os
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PIPELINE_WORK = REPO_ROOT / "pipeline_work"
DB_PATH = REPO_ROOT / "db" / "m4e.db"

sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic SDK required. Install: pip install anthropic")
    sys.exit(1)

from card_extractor import extract_crew_card_back


def find_crew_back_pngs(faction: str = None) -> list:
    """Find all crew card back PNGs in pipeline_work."""
    results = []

    if faction:
        search_dirs = [PIPELINE_WORK / faction]
    else:
        # Search both root and faction subdirectories
        search_dirs = [PIPELINE_WORK]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for png in sorted(search_dir.rglob("*Crew*_back.png")):
            merged_json = png.parent / png.name.replace("_back.png", "_merged.json")
            results.append({
                "back_png": png,
                "merged_json": merged_json,
            })
    return results


def get_crew_card_name(merged_json: Path) -> str:
    """Read the crew card name from the existing merged JSON."""
    if merged_json.exists():
        with open(merged_json, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("name", "")
    return ""


def update_crew_tokens(conn, crew_card_name: str, tokens: list) -> dict:
    """Replace tokens for a crew card in the database."""
    c = conn.cursor()
    c.execute("SELECT id FROM crew_cards WHERE name=?", (crew_card_name,))
    row = c.fetchone()
    if not row:
        return {"status": "not_found", "name": crew_card_name}

    crew_id = row[0]

    # Delete existing tokens
    old_count = c.execute(
        "SELECT COUNT(*) FROM crew_tokens WHERE crew_card_id=?", (crew_id,)
    ).fetchone()[0]
    c.execute("DELETE FROM crew_tokens WHERE crew_card_id=?", (crew_id,))

    # Insert new tokens
    for token in tokens:
        c.execute(
            "INSERT INTO crew_tokens (crew_card_id, name, text) VALUES (?,?,?)",
            (crew_id, token["name"], token["text"])
        )

    conn.commit()
    return {
        "status": "updated", "crew_id": crew_id,
        "name": crew_card_name, "token_count": len(tokens),
        "old_count": old_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill crew card token definitions")
    parser.add_argument("--apply", action="store_true", help="Update database")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, don't update DB")
    parser.add_argument("--faction", help="Process only one faction subfolder")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between API calls (default: 1.5)")
    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    # Setup API client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # Find back PNGs
    backs = find_crew_back_pngs(args.faction)
    print(f"Found {len(backs)} crew card back PNGs")

    # Connect to DB
    conn = None
    if args.apply:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA foreign_keys=ON")

    # Process
    stats = {"extracted": 0, "updated": 0, "errors": 0, "not_found": 0, "skipped": 0}
    start_time = time.time()

    for i, entry in enumerate(backs):
        back_png = entry["back_png"]
        crew_name = get_crew_card_name(entry["merged_json"])

        if not crew_name:
            print(f"  [{i+1}/{len(backs)}] SKIP {back_png.name} (no merged JSON or missing name)")
            stats["skipped"] += 1
            continue

        print(f"  [{i+1}/{len(backs)}] {back_png.name} -> '{crew_name}'")

        # Extract tokens from back
        result = extract_crew_card_back(client, str(back_png))

        if "error" in result:
            print(f"    ERROR: {result['error']}")
            stats["errors"] += 1
            continue

        tokens = result.get("tokens", [])
        token_names = [t["name"] for t in tokens]
        print(f"    {len(tokens)} tokens: {', '.join(token_names)}")
        stats["extracted"] += 1

        # Update DB
        if args.apply and conn:
            db_result = update_crew_tokens(conn, crew_name, tokens)
            if db_result["status"] == "updated":
                stats["updated"] += 1
                if db_result["old_count"]:
                    print(f"    DB: replaced {db_result['old_count']} -> {db_result['token_count']} tokens")
                else:
                    print(f"    DB: inserted {db_result['token_count']} tokens")
            elif db_result["status"] == "not_found":
                print(f"    WARNING: '{crew_name}' not found in crew_cards table")
                stats["not_found"] += 1

        # Rate limiting
        if i < len(backs) - 1:
            time.sleep(args.delay)

    if conn:
        conn.close()

    elapsed = time.time() - start_time

    # Summary
    print(f"\n{'='*50}")
    print(f"BACKFILL SUMMARY")
    print(f"{'='*50}")
    print(f"  Processed:    {len(backs)}")
    print(f"  Extracted:    {stats['extracted']}")
    print(f"  Updated DB:   {stats['updated']}")
    print(f"  Not found:    {stats['not_found']}")
    print(f"  Skipped:      {stats['skipped']}")
    print(f"  Errors:       {stats['errors']}")
    print(f"  Time:         {elapsed:.1f}s")


if __name__ == "__main__":
    main()
